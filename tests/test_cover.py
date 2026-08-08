"""Tests for the cover entity."""
from __future__ import annotations

from unittest.mock import MagicMock

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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from .conftest import TEST_SHUTTER_ID

ENTITY_ID = "cover.living_room"


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        COVER_DOMAIN,
        service,
        {ATTR_ENTITY_ID: ENTITY_ID, **data},
        blocking=True,
    )


async def test_entity_attributes(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """The entity is a blind supporting open/close/stop/set_position."""
    await _setup(hass, config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes[ATTR_DEVICE_CLASS] == CoverDeviceClass.BLIND
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    # assumed_state=False, so the attribute is not published.
    assert "assumed_state" not in state.attributes


async def test_defaults_to_open_without_restored_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """On a first start the shutter is reported open rather than unknown."""
    await _setup(hass, config_entry)

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
    mock_controller: MagicMock,
    restored: str,
    expected_position: int,
) -> None:
    """The previous state is restored on restart."""
    mock_restore_cache(hass, (_state(restored),))

    await _setup(hass, config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == restored
    assert state.attributes[ATTR_CURRENT_POSITION] == expected_position


def _state(state: str):
    from homeassistant.core import State

    return State(ENTITY_ID, state)


async def test_open_and_close_send_the_commands(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Opening and closing writes the matching command on the serial port."""
    await _setup(hass, config_entry)

    await _call(hass, SERVICE_CLOSE_COVER)
    assert hass.states.get(ENTITY_ID).state == STATE_CLOSED
    mock_controller.send_command.assert_called_with(TEST_SHUTTER_ID, "close")

    await _call(hass, SERVICE_OPEN_COVER)
    assert hass.states.get(ENTITY_ID).state == STATE_OPEN
    mock_controller.send_command.assert_called_with(TEST_SHUTTER_ID, "open")


async def test_icon_follows_the_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """The roller-shutter icon reflects open/closed."""
    await _setup(hass, config_entry)

    assert hass.states.get(ENTITY_ID).attributes[ATTR_ICON] == "mdi:window-shutter-open"

    await _call(hass, SERVICE_CLOSE_COVER)

    assert hass.states.get(ENTITY_ID).attributes[ATTR_ICON] == "mdi:window-shutter"


async def test_stop_keeps_the_cached_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Stopping sends the command without touching the cached state."""
    await _setup(hass, config_entry)
    await _call(hass, SERVICE_CLOSE_COVER)

    await _call(hass, SERVICE_STOP_COVER)

    mock_controller.send_command.assert_called_with(TEST_SHUTTER_ID, "stop")
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
    mock_controller: MagicMock,
    position: int,
    expected_action: str,
    expected_state: str,
) -> None:
    """A position setpoint is snapped to fully open or fully closed."""
    await _setup(hass, config_entry)

    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: position})

    mock_controller.send_command.assert_called_with(TEST_SHUTTER_ID, expected_action)
    state = hass.states.get(ENTITY_ID)
    assert state.state == expected_state
    assert state.attributes[ATTR_CURRENT_POSITION] in (0, 100)


async def test_failed_command_rolls_back_the_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """A serial failure restores the state published optimistically."""
    await _setup(hass, config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_OPEN

    mock_controller.send_command.side_effect = serial.SerialException("no module")

    with pytest.raises(HomeAssistantError):
        await _call(hass, SERVICE_CLOSE_COVER)

    assert hass.states.get(ENTITY_ID).state == STATE_OPEN


async def test_unexpected_response_rolls_back_the_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """A response without "Sending" is treated as a failure."""
    await _setup(hass, config_entry)
    mock_controller.send_command.return_value = "ERR"

    with pytest.raises(HomeAssistantError):
        await _call(hass, SERVICE_CLOSE_COVER)

    assert hass.states.get(ENTITY_ID).state == STATE_OPEN


async def test_no_entity_without_shutters(
    hass: HomeAssistant, mock_controller: MagicMock
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
        data={CONF_PORT: "/dev/ttyUSB1", CONF_BAUDRATE: 115200},
        options={CONF_SHUTTERS: []},
    )
    await _setup(hass, entry)

    assert hass.states.async_entity_ids("cover") == []
