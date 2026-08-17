"""Diagnostic sensors: what the radio reports about each shutter.

The firmware puts a rolling counter on every event and an RSSI on every frame
it hears. Neither says anything about the shutter's position, so they are
diagnostics rather than state: they are what you look at when a shutter stops
responding, or to tell whether a remote is in range.

They are marked as diagnostics, so Home Assistant files them under the device's
diagnostic section rather than mixing them in with the shutter's controls.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_NAME,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
    SIGNAL_SHUTTER_EVENT,
)
from .hub import CC1101Hub, ShutterTelemetry

SIGNAL_STRENGTH_DBM = "dBm"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the diagnostic sensors of every configured shutter."""
    hub: CC1101Hub = hass.data[DOMAIN][entry.entry_id]

    entities: list[ShutterDiagnosticSensor] = []
    for cover in entry.options.get(CONF_SHUTTERS, []):
        shutter_id = str(cover[CONF_SHUTTER_ID])
        name = cover[CONF_NAME]
        entities.append(CounterSensor(hub, entry.entry_id, shutter_id, name))
        entities.append(SignalStrengthSensor(hub, entry.entry_id, shutter_id, name))

    async_add_entities(entities)


class ShutterDiagnosticSensor(SensorEntity):
    """Base class: reads the hub's telemetry, refreshed by firmware events."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hub: CC1101Hub,
        entry_id: str,
        shutter_id: str,
        name: str,
        key: str,
    ) -> None:
        self._hub = hub
        self._entry_id = entry_id
        self._shutter_id = shutter_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{shutter_id}_{key}"
        # Same identifiers as the cover, so these land on the shutter's device.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{shutter_id}")},
            name=name,
            manufacturer="CC1101",
            model="Rolling Shutter",
            serial_number=shutter_id,
        )

    @property
    def telemetry(self) -> ShutterTelemetry:
        """Live telemetry for this shutter."""
        return self._hub.telemetry_for(self._shutter_id)

    async def async_added_to_hass(self) -> None:
        """Refresh whenever the firmware says something about this shutter."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SHUTTER_EVENT.format(self._entry_id, self._shutter_id),
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, event: dict[str, Any]) -> None:
        """The hub has already folded the event into the telemetry."""
        self.async_write_ha_state()


class CounterSensor(ShutterDiagnosticSensor):
    """The shutter's rolling counter, as last seen by the firmware."""

    _attr_icon = "mdi:counter"

    def __init__(self, hub: CC1101Hub, entry_id: str, sid: str, name: str) -> None:
        super().__init__(hub, entry_id, sid, name, "counter")

    @property
    def native_value(self) -> int | None:
        """0-255, or unknown until a frame is sent or heard.

        Deliberately not restored across restarts: the firmware does not keep
        its own table either, so a stale value would be a lie.
        """
        return self.telemetry.counter

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Where the value came from — a frame we sent, or one on the air."""
        return {"source": self.telemetry.counter_source}


class SignalStrengthSensor(ShutterDiagnosticSensor):
    """RSSI of the last frame heard from this shutter's remotes."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DBM

    def __init__(self, hub: CC1101Hub, entry_id: str, sid: str, name: str) -> None:
        super().__init__(hub, entry_id, sid, name, "signal_strength")

    @property
    def native_value(self) -> int | None:
        """RSSI in dBm, or unknown until a remote has been heard.

        Only frames received on the air carry a signal level; our own
        transmissions report none, so sending a command leaves this untouched.
        """
        return self.telemetry.rssi

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which command the frame behind the current reading carried."""
        return {"last_command": self.telemetry.last_command}
