"""Tests for the cover entity."""
from __future__ import annotations

import pytest
import serial

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    DOMAIN as COVER_DOMAIN,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_ICON,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
    STATE_CLOSED,
    STATE_OPEN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from .conftest import TEST_SHUTTER_ID, FakeFirmware

ENTITY_ID = "cover.living_room"


async def call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        COVER_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True
    )


async def test_entity_attributes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The entity is a blind supporting open/close/stop/set_position."""
    await setup_entry(config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes[ATTR_DEVICE_CLASS] == CoverDeviceClass.BLIND
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    assert "assumed_state" not in state.attributes


async def test_open_and_close_address_the_shutter_by_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Commands carry the 4-byte radio ID, not an index."""
    await setup_entry(config_entry)

    await call(hass, SERVICE_CLOSE_COVER)
    assert hass.states.get(ENTITY_ID).state == STATE_CLOSED
    assert firmware.last_command == (TEST_SHUTTER_ID, "close")

    await call(hass, SERVICE_OPEN_COVER)
    assert hass.states.get(ENTITY_ID).state == STATE_OPEN
    assert firmware.last_command == (TEST_SHUTTER_ID, "open")


@pytest.mark.parametrize(
    ("heard", "expected"),
    [("close", STATE_CLOSED), ("open", STATE_OPEN)],
)
async def test_state_follows_the_original_remote(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
    heard: str,
    expected: str,
) -> None:
    """A frame from a physical remote updates the entity."""
    await setup_entry(config_entry)
    # Start from the opposite state so the change is observable.
    await call(hass, SERVICE_OPEN_COVER if heard == "close" else SERVICE_CLOSE_COVER)

    firmware.emit_rx(TEST_SHUTTER_ID, heard)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == expected


async def test_remote_stop_keeps_the_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Stop heard on the air says nothing about the position."""
    await setup_entry(config_entry)
    await call(hass, SERVICE_CLOSE_COVER)

    firmware.emit_rx(TEST_SHUTTER_ID, "stop")
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_CLOSED


async def test_frames_for_another_shutter_are_ignored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Only this shutter's ID drives this entity."""
    await setup_entry(config_entry)
    await call(hass, SERVICE_OPEN_COVER)

    firmware.emit_rx("0a1b2c01", "close")
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_OPEN


async def test_unknown_command_on_the_air_is_ignored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A fourth button would not be mistaken for open or close."""
    await setup_entry(config_entry)
    await call(hass, SERVICE_OPEN_COVER)

    firmware.emit_rx(TEST_SHUTTER_ID, "0x08")
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_OPEN


async def test_defaults_to_open_without_restored_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """On a first start the shutter is reported open rather than unknown."""
    await setup_entry(config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_OPEN
    assert state.attributes[ATTR_CURRENT_POSITION] == 100


@pytest.mark.parametrize(
    ("restored", "expected_position"),
    [(STATE_CLOSED, 0), (STATE_OPEN, 100)],
)
async def test_state_is_restored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
    restored: str,
    expected_position: int,
) -> None:
    """The previous state is restored on restart."""
    mock_restore_cache(hass, (State(ENTITY_ID, restored),))

    await setup_entry(config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == restored
    assert state.attributes[ATTR_CURRENT_POSITION] == expected_position


async def test_icon_follows_the_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The roller-shutter icon reflects open/closed."""
    await setup_entry(config_entry)
    assert hass.states.get(ENTITY_ID).attributes[ATTR_ICON] == "mdi:window-shutter-open"

    await call(hass, SERVICE_CLOSE_COVER)

    assert hass.states.get(ENTITY_ID).attributes[ATTR_ICON] == "mdi:window-shutter"


async def test_stop_keeps_the_cached_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Stopping sends the command without touching the cached state."""
    await setup_entry(config_entry)
    await call(hass, SERVICE_CLOSE_COVER)

    await call(hass, SERVICE_STOP_COVER)

    assert firmware.last_command == (TEST_SHUTTER_ID, "stop")
    assert hass.states.get(ENTITY_ID).state == STATE_CLOSED


@pytest.mark.parametrize(
    ("position", "expected_action", "expected_state"),
    [
        (0, "close", STATE_CLOSED),
        (49, "close", STATE_CLOSED),
        (50, "open", STATE_OPEN),
        (100, "open", STATE_OPEN),
    ],
)
async def test_set_position_snaps_to_the_extremes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
    position: int,
    expected_action: str,
    expected_state: str,
) -> None:
    """A position setpoint is snapped to fully open or fully closed."""
    await setup_entry(config_entry)

    await call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: position})

    assert firmware.last_command == (TEST_SHUTTER_ID, expected_action)
    state = hass.states.get(ENTITY_ID)
    assert state.state == expected_state
    assert state.attributes[ATTR_CURRENT_POSITION] in (0, 100)


async def test_failed_command_rolls_back_the_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A serial failure restores the state published optimistically."""
    await setup_entry(config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_OPEN

    firmware.fail_with = serial.SerialException("no module")

    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_CLOSE_COVER)

    assert hass.states.get(ENTITY_ID).state == STATE_OPEN


async def test_no_entity_without_shutters(
    hass: HomeAssistant, firmware: FakeFirmware, setup_entry
) -> None:
    """An entry without any declared shutter creates no entity."""
    from custom_components.cc1101_rolling_shutter.const import (
        CONF_BAUDRATE,
        CONF_PORT,
        CONF_SHUTTERS,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_PORT: "/dev/ttyUSB1", CONF_BAUDRATE: 115200},
        options={CONF_SHUTTERS: []},
    )
    await setup_entry(entry)

    assert hass.states.async_entity_ids("cover") == []
