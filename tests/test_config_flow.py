"""Tests for the config and options flows."""
from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter.const import (
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DEFAULT_BAUDRATE,
    DOMAIN,
)

from .conftest import TEST_BAUDRATE, TEST_PORT, TEST_SHUTTER_ID


async def test_user_flow_creates_the_entry(
    hass: HomeAssistant, mock_controller: MagicMock
) -> None:
    """The user flow stores the port and starts with no shutter."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"CC1101 ({TEST_PORT})"
    assert result["data"] == {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE}
    assert result["options"] == {CONF_SHUTTERS: []}


async def test_same_port_cannot_be_configured_twice(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """A serial port can only be set up once."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_port(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Reconfiguring keeps the shutters and updates the port."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: 57600},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PORT] == "/dev/ttyACM0"
    assert config_entry.data[CONF_BAUDRATE] == 57600
    assert config_entry.unique_id == "/dev/ttyACM0"
    # The shutter (and therefore its device) survived the change.
    assert len(config_entry.options[CONF_SHUTTERS]) == 1


async def test_reconfigure_rejects_a_port_used_by_another_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Two entries cannot share the same serial port."""
    config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="/dev/ttyACM0",
        data={CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: DEFAULT_BAUDRATE},
        options={CONF_SHUTTERS: []},
    )
    other.add_to_hass(hass)

    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: DEFAULT_BAUDRATE},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}


async def test_options_add_shutter(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """The options flow appends a shutter, trimming the input."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_shutter"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHUTTER_ID: " 5 ", CONF_NAME: " Kitchen "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHUTTERS] == [
        {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"},
        {CONF_SHUTTER_ID: "5", CONF_NAME: "Kitchen"},
    ]


async def test_options_add_shutter_rejects_a_duplicate_id(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Two shutters cannot share the same radio ID."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_shutter"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Duplicate"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_exists"}


async def test_options_remove_shutter(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """The options flow removes the selected shutters."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_shutter"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"to_remove": [TEST_SHUTTER_ID]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHUTTERS] == []
    # The platform no longer provides the entity: its registry entry stays
    # behind as unavailable until the device is deleted from the UI.
    assert hass.states.get("cover.living_room").state == STATE_UNAVAILABLE


async def test_options_remove_shutter_without_any(
    hass: HomeAssistant, mock_controller: MagicMock
) -> None:
    """Removing a shutter aborts when there is none."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="/dev/ttyUSB9",
        data={CONF_PORT: "/dev/ttyUSB9", CONF_BAUDRATE: DEFAULT_BAUDRATE},
        options={CONF_SHUTTERS: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_shutter"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_shutters"
