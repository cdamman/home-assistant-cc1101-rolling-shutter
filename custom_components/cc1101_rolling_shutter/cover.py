"""Cover platform: one rolling shutter = one entity."""
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

from .const import (
    CONF_NAME,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
    EXPECTED_RESPONSE,
)
from .serial_controller import SerialController

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one entity per shutter declared in the options."""
    controller: SerialController = hass.data[DOMAIN][entry.entry_id]
    shutters = entry.options.get(CONF_SHUTTERS, [])

    entities = [
        CC1101ShutterCover(
            controller=controller,
            entry_id=entry.entry_id,
            shutter_id=str(shutter[CONF_SHUTTER_ID]),
            name=shutter[CONF_NAME],
        )
        for shutter in shutters
    ]
    async_add_entities(entities)


class CC1101ShutterCover(CoverEntity, RestoreEntity):
    """A rolling shutter driven by the CC1101 module.

    The module reports no state at all, so we are in "assumed state". The
    state is cached after each transition and restored when Home Assistant
    restarts, through ``RestoreEntity``.
    """

    # Note: this setting also drives the classification on the Google Home
    # side. BLIND is not part of the DEVICE_CLASS_TO_GOOGLE_TYPES table of the
    # google_assistant component, so it falls back to the default type of the
    # "cover" domain => action.devices.types.BLINDS, i.e. "Blind" in Google
    # Home (SHUTTER, on the other hand, mapped to .../SHUTTER, i.e. "Shutter").
    _attr_device_class = CoverDeviceClass.BLIND
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
    _attr_assumed_state = False
    _attr_should_poll = False
    # The entity carries the name of its device (one device = one shutter).
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        controller: SerialController,
        entry_id: str,
        shutter_id: str,
        name: str,
    ) -> None:
        self._controller = controller
        self._shutter_id = shutter_id
        self._attr_unique_id = f"{entry_id}_{shutter_id}"
        # None => state unknown as long as no command has been sent and no
        # previous state has been restored.
        self._attr_is_closed: bool | None = None
        # One distinct device per shutter: a unique identifier per shutter.
        # Each one can therefore be assigned to a different room.
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
                "Shutter %s: restored state = %s", self._shutter_id, last_state.state
            )
        else:
            # Nothing to restore: start from a concrete state rather than
            # "unknown" (with assumed_state=False, "unknown" would make the
            # shutter show up as offline in Google Home). Set to True to
            # start "closed".
            self._attr_is_closed = False
            _LOGGER.debug(
                "Shutter %s: no state restored, defaulting to open",
                self._shutter_id,
            )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter: send ``<id> open``."""
        await self._send("open")
        self._attr_is_closed = False
        self.async_write_ha_state()  # cache the state and display it

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter: send ``<id> close``."""
        await self._send("close")
        self._attr_is_closed = True
        self.async_write_ha_state()  # cache the state and display it

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shutter: send ``<id> stop``.

        The cached state is left untouched: there is no way to know at which
        position the shutter stopped, so we keep the last known state
        (open/closed/unknown).
        """
        await self._send("stop")

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

    async def _send(self, action: str) -> None:
        """Send the command on the executor and validate the response."""
        try:
            response = await self.hass.async_add_executor_job(
                self._controller.send_command, self._shutter_id, action
            )
        except Exception as err:  # noqa: BLE001 - surfaced as a HA error
            raise HomeAssistantError(
                f"Serial link failure for shutter {self._shutter_id}: {err}"
            ) from err

        if EXPECTED_RESPONSE not in response:
            raise HomeAssistantError(
                f"Unexpected response from shutter {self._shutter_id} "
                f"(expected {EXPECTED_RESPONSE!r}, got {response!r})"
            )
