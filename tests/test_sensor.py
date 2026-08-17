"""Tests for the per-shutter diagnostic sensors."""
from __future__ import annotations

from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter.const import DOMAIN

from .conftest import OTHER_SHUTTER_ID, TEST_SHUTTER_ID, FakeFirmware

COUNTER = "sensor.living_room_rf_code_rolling_counter"
RSSI = "sensor.living_room_remote_signal_strength"


async def test_sensors_are_diagnostic_and_enabled(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Both sensors are live out of the box, filed under diagnostics."""
    await setup_entry(config_entry)

    registry = er.async_get(hass)
    for entity_id in (COUNTER, RSSI):
        entry_ = registry.async_get(entity_id)
        assert entry_ is not None, f"{entity_id} was never registered"
        assert entry_.disabled_by is None
        assert entry_.entity_category is er.EntityCategory.DIAGNOSTIC
        assert hass.states.get(entity_id) is not None


async def test_sensors_share_the_device_with_the_cover(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The diagnostics belong to the shutter, not to a device of their own."""
    await setup_entry(config_entry)

    registry = er.async_get(hass)
    devices = {
        registry.async_get(entity_id).device_id
        for entity_id in (COUNTER, RSSI, "cover.living_room")
    }
    assert len(devices) == 1


async def test_values_are_unknown_until_the_radio_says_something(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Nothing is restored: a stale counter would be a lie."""
    await setup_entry(config_entry)

    assert hass.states.get(COUNTER).state == STATE_UNKNOWN
    assert hass.states.get(RSSI).state == STATE_UNKNOWN


async def test_counter_follows_frames_heard_on_the_air(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A remote press resynchronises the counter, and says where it came from."""
    await setup_entry(config_entry)

    firmware.emit_rx(TEST_SHUTTER_ID, "open", counter=51)
    await hass.async_block_till_done()

    state = hass.states.get(COUNTER)
    assert state.state == "51"
    assert state.attributes["source"] == "air"


async def test_counter_follows_our_own_transmissions(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Sending a command advances the counter too, tagged as ours."""
    await setup_entry(config_entry)

    hub = hass.data[DOMAIN][config_entry.entry_id]
    await hub.async_send(TEST_SHUTTER_ID, "close")
    await hass.async_block_till_done()

    state = hass.states.get(COUNTER)
    assert state.state == "1"  # the fake firmware acknowledges with counter 1
    assert state.attributes["source"] == "sent"


async def test_signal_strength_reports_dbm(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """RSSI is a proper signal-strength measurement."""
    await setup_entry(config_entry)

    firmware.emit_rx(TEST_SHUTTER_ID, "open", rssi=-58)
    await hass.async_block_till_done()

    state = hass.states.get(RSSI)
    assert state.state == "-58"
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "dBm"
    assert state.attributes[ATTR_DEVICE_CLASS] == "signal_strength"


async def test_signal_strength_shows_only_the_latest_frame(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """No history is kept: each frame replaces the reading, whatever it is."""
    await setup_entry(config_entry)

    firmware.emit_rx(TEST_SHUTTER_ID, "open", rssi=-50)
    firmware.emit_rx(TEST_SHUTTER_ID, "close", rssi=-70)
    firmware.emit_rx(TEST_SHUTTER_ID, "stop", rssi=-61)
    await hass.async_block_till_done()

    state = hass.states.get(RSSI)
    assert state.state == "-61"
    assert state.attributes["last_command"] == "stop"
    # The command that carried the reading is the only extra context kept.
    assert set(state.attributes) >= {"last_command"}
    assert not [key for key in state.attributes if key.startswith("rssi_")]


async def test_our_own_transmissions_leave_the_signal_untouched(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A "tx" event carries no RSSI, so it must not clear the last one."""
    await setup_entry(config_entry)
    firmware.emit_rx(TEST_SHUTTER_ID, "open", rssi=-58)
    await hass.async_block_till_done()

    hub = hass.data[DOMAIN][config_entry.entry_id]
    await hub.async_send(TEST_SHUTTER_ID, "close")
    await hass.async_block_till_done()

    assert hass.states.get(RSSI).state == "-58"


async def test_another_shutter_does_not_move_these_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Telemetry is per shutter, including for neighbours on the air."""
    await setup_entry(config_entry)
    firmware.emit_rx(TEST_SHUTTER_ID, "open", counter=10, rssi=-40)
    await hass.async_block_till_done()

    firmware.emit_rx(OTHER_SHUTTER_ID, "close", counter=99, rssi=-90)
    await hass.async_block_till_done()

    assert hass.states.get(COUNTER).state == "10"
    assert hass.states.get(RSSI).state == "-40"


async def test_no_sensors_without_shutters(
    hass: HomeAssistant, firmware: FakeFirmware, setup_entry
) -> None:
    """An entry with no shutter declares no diagnostics."""
    from custom_components.cc1101_rolling_shutter.const import (
        CONF_BAUDRATE,
        CONF_PORT,
        CONF_SHUTTERS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_PORT: "/dev/ttyUSB2", CONF_BAUDRATE: 115200},
        options={CONF_SHUTTERS: []},
    )
    await setup_entry(entry)

    assert hass.states.async_entity_ids("sensor") == []
