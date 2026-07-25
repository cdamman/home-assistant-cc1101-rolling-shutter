"""Cover platform: one CC1101 shutter = one entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .backend import SerialShutterBackend
from .const import (
    CONF_NAME,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one entity per shutter declared in the options."""
    data = hass.data[DOMAIN][entry.entry_id]
    controller = data["controller"]
    lock = data["lock"]  # shared => RF transmissions serialized per module

    entities: list[AssumedShutterCover] = []
    for cover in entry.options.get(CONF_SHUTTERS, []):
        shutter_id = str(cover[CONF_SHUTTER_ID])
        entities.append(
            AssumedShutterCover(
                backend=SerialShutterBackend(hass, controller, shutter_id, lock),
                entry_id=entry.entry_id,
                key=shutter_id,
                name=cover[CONF_NAME],
            )
        )

    async_add_entities(entities)


class AssumedShutterCover(CoverEntity, RestoreEntity):
    """A CC1101 shutter whose state is not reported by the hardware.

    The state and the position (0 = closed, 100 = open) are *inferred* from
    our own commands, cached after each action and restored on restart through
    ``RestoreEntity``. The module never reports any state. A position setpoint
    is snapped to one of the two extremes (see ``async_set_cover_position``).
    """

    # Note: this setting also drives the classification on the Google Home
    # side. BLIND is not part of the DEVICE_CLASS_TO_GOOGLE_TYPES table of the
    # google_assistant component, so it falls back to the default type of the
    # "cover" domain => action.devices.types.BLINDS, i.e. "Blind" in Google
    # Home (SHUTTER, on the other hand, mapped to .../SHUTTER, i.e. "Shutter").
    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        # SET_POSITION acts as a "lever" so that the google_assistant component
        # computes isRunning=True at all times (hence "Stop" always available)
        # while keeping assumed_state=False (hence the open/closed state stays
        # visible in Google Home). The hardware has no real position: the
        # setpoint is snapped to open/closed (see async_set_cover_position).
        | CoverEntityFeature.SET_POSITION
    )
    # assumed_state = False: we expose a "real" state/position (inferred from
    # our commands) so that Google Home displays open/closed. Combined with
    # SET_POSITION above, this also keeps "Stop" permanently available.
    # Trade-off on the Home Assistant side: when idle (position 0% or 100%),
    # the redundant button is greyed out — a shutter already "closed" cannot be
    # closed again through that button (the slider stays usable at all times).
    _attr_assumed_state = False
    _attr_should_poll = False
    # The entity carries the name of its device (one device = one shutter).
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        backend: SerialShutterBackend,
        entry_id: str,
        key: str,
        name: str,
    ) -> None:
        self._backend = backend
        # Human-readable identifier for the logs (radio ID of the shutter).
        self._log_id = key
        self._attr_unique_id = f"{entry_id}_{key}"
        # None => state unknown as long as no command has been sent and no
        # previous state has been restored.
        self._attr_is_closed: bool | None = None
        # One distinct device per shutter: each can be assigned to a room.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=name,
            manufacturer="CC1101",
            model="Rolling Shutter",
        )

    @property
    def icon(self) -> str:
        """Roller-shutter icon in the Home Assistant UI, based on the state.

        The BLIND device class (chosen so that Google Home classifies the
        device as a "Blind") would give a blind icon by default. We override it
        here to get the roller-shutter icons back, and make them follow the
        state:
          - closed -> mdi:window-shutter       (slats down)
          - open   -> mdi:window-shutter-open  (slats up)
        This override is purely cosmetic on the HA side and has no effect on
        the classification sent to Google Home.
        """
        if self._attr_is_closed:
            return "mdi:window-shutter"
        return "mdi:window-shutter-open"

    @property
    def current_cover_position(self) -> int | None:
        """Position exposed to HA and Google Home: 0 = closed, 100 = open.

        The hardware has no intermediate position; we simply mirror the cached
        binary state. Publishing a position is required for SET_POSITION (and
        therefore for "Stop" being permanently available) to make sense, and
        for Google Home to display the state.
        """
        if self._attr_is_closed is None:
            return None
        return 0 if self._attr_is_closed else 100

    async def async_added_to_hass(self) -> None:
        """Restore the last known state from the Home Assistant cache."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (STATE_OPEN, STATE_CLOSED):
            self._attr_is_closed = last_state.state == STATE_CLOSED
            _LOGGER.debug(
                "Shutter %s: restored state = %s", self._log_id, last_state.state
            )
        else:
            # Nothing to restore (very first start): start from a concrete
            # state rather than "unknown". This matters with
            # assumed_state=False: an "unknown" state would make the Google
            # Home state query fail (the shutter would show up as offline).
            # Set to True to start "closed".
            self._attr_is_closed = False
            _LOGGER.debug(
                "Shutter %s: no state restored, defaulting to open", self._log_id
            )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter."""
        await self._optimistic_send("open", is_closed=False)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter."""
        await self._optimistic_send("close", is_closed=True)

    async def _optimistic_send(self, action: str, is_closed: bool) -> None:
        """Publish the state BEFORE sending the (possibly slow) command.

        Important detail for Google Home: when state reporting is enabled, the
        google_assistant component runs the command in a NON-blocking way and
        immediately reads the state back for its response. If we only updated
        the state AFTER the command had been sent, that read would return the
        old state and the tile would flicker back to the previous state before
        correcting itself. So we publish the optimistic state first, then send
        the command; if the backend fails, we roll back to the previous state.
        """
        previous = self._attr_is_closed
        self._attr_is_closed = is_closed
        self.async_write_ha_state()
        try:
            await self._backend.async_send(action)
        except HomeAssistantError:
            self._attr_is_closed = previous
            self.async_write_ha_state()
            raise

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shutter.

        The cached state is left untouched: there is no way to know at which
        position the shutter stopped, so we keep the last known state
        (open/closed/unknown).
        """
        await self._backend.async_send("stop")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Position setpoint: snapped to open/closed (50% threshold).

        The hardware knows no intermediate position:
          - position < 50   -> close the shutter;
          - position >= 50  -> open the shutter (50 included).
        The displayed position then snaps back to 0 or 100 through
        ``current_cover_position``.
        """
        position = kwargs[ATTR_POSITION]
        if position < 50:
            await self.async_close_cover()
        else:
            await self.async_open_cover()
