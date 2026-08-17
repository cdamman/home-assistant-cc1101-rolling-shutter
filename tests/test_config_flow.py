"""Tests for the config and options flows."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter.config_flow import CONF_DISCOVERED
from custom_components.cc1101_rolling_shutter.const import (
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DEFAULT_BAUDRATE,
    DOMAIN,
)

from .conftest import (
    OTHER_SHUTTER_ID,
    TEST_BAUDRATE,
    TEST_PORT,
    TEST_SHUTTER_ID,
    FakeFirmware,
)


async def open_add_shutter(hass: HomeAssistant, entry: MockConfigEntry):
    """Walk the options menu to the add-a-shutter form."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_shutter"}
    )


async def test_user_flow_creates_the_entry(
    hass: HomeAssistant, firmware: FakeFirmware
) -> None:
    """The user flow stores the port and starts with no shutter."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"CC1101 ({TEST_PORT})"
    assert result["data"] == {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE}
    assert result["options"] == {CONF_SHUTTERS: []}
    assert result["result"].version == 2


async def test_same_port_cannot_be_configured_twice(
    hass: HomeAssistant, config_entry: MockConfigEntry, firmware: FakeFirmware
) -> None:
    """A serial port can only be set up once."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_port(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Reconfiguring keeps the shutters and updates the port."""
    await setup_entry(config_entry)

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: 57600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PORT] == "/dev/ttyACM0"
    assert config_entry.unique_id == "/dev/ttyACM0"
    assert len(config_entry.options[CONF_SHUTTERS]) == 1


async def test_reconfigure_rejects_a_port_used_by_another_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, firmware: FakeFirmware
) -> None:
    """Two entries cannot share the same serial port."""
    config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="/dev/ttyACM0",
        data={CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: DEFAULT_BAUDRATE},
        options={CONF_SHUTTERS: []},
    )
    other.add_to_hass(hass)

    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PORT: "/dev/ttyACM0", CONF_BAUDRATE: DEFAULT_BAUDRATE}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}


async def test_add_shutter_by_typing_an_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """An ID can be typed in, with separators, and is normalised."""
    await setup_entry(config_entry)
    result = await open_add_shutter(hass, config_entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SHUTTER_ID: " 0A:1B:2C:01 ", CONF_NAME: " Kitchen "},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHUTTERS] == [
        {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"},
        {CONF_SHUTTER_ID: OTHER_SHUTTER_ID, CONF_NAME: "Kitchen"},
    ]


async def test_add_shutter_from_discovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A shutter heard on the air can be picked from the list."""
    await setup_entry(config_entry)
    firmware.emit_rx(OTHER_SHUTTER_ID, "open")
    await hass.async_block_till_done()

    result = await open_add_shutter(hass, config_entry)
    # The discovered shutter is offered as a choice.
    assert CONF_DISCOVERED in str(result["data_schema"].schema)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_DISCOVERED: OTHER_SHUTTER_ID, CONF_NAME: "Bedroom"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHUTTERS][-1] == {
        CONF_SHUTTER_ID: OTHER_SHUTTER_ID,
        CONF_NAME: "Bedroom",
    }
    assert len(hass.states.async_entity_ids("cover")) == 2


async def test_discovery_list_is_empty_without_traffic(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """With nothing heard, only the manual field is offered."""
    await setup_entry(config_entry)

    result = await open_add_shutter(hass, config_entry)

    assert CONF_DISCOVERED not in str(result["data_schema"].schema)


async def test_add_shutter_rejects_an_invalid_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The old index format no longer passes validation."""
    await setup_entry(config_entry)
    result = await open_add_shutter(hass, config_entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHUTTER_ID: "4", CONF_NAME: "Bedroom"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_id"}


async def test_add_shutter_requires_an_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Submitting only a name is rejected."""
    await setup_entry(config_entry)
    result = await open_add_shutter(hass, config_entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Bedroom"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "id_required"}


async def test_add_shutter_rejects_a_duplicate_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Two shutters cannot share the same radio ID."""
    await setup_entry(config_entry)
    result = await open_add_shutter(hass, config_entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Duplicate"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_exists"}


async def test_configured_shutter_leaves_the_discovery_list(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Once added, a shutter is no longer offered as a discovery."""
    await setup_entry(config_entry)
    firmware.emit_rx(OTHER_SHUTTER_ID, "open")
    await hass.async_block_till_done()

    result = await open_add_shutter(hass, config_entry)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DISCOVERED: OTHER_SHUTTER_ID, CONF_NAME: "Bedroom"}
    )
    await hass.async_block_till_done()

    hub = hass.data[DOMAIN][config_entry.entry_id]
    assert hub.available_discoveries() == []


async def test_options_remove_shutter(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The options flow removes the selected shutters."""
    await setup_entry(config_entry)

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
    hass: HomeAssistant, firmware: FakeFirmware, setup_entry
) -> None:
    """Removing a shutter aborts when there is none."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="/dev/ttyUSB9",
        data={CONF_PORT: "/dev/ttyUSB9", CONF_BAUDRATE: DEFAULT_BAUDRATE},
        options={CONF_SHUTTERS: []},
    )
    await setup_entry(entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_shutter"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_shutters"


async def test_add_shutter_works_when_the_entry_is_not_loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry, firmware: FakeFirmware
) -> None:
    """A shutter can still be added if the serial port could not be opened.

    There is no hub to ask for discoveries in that case, so only the manual
    field is offered — but the flow must not blow up.
    """
    config_entry.add_to_hass(hass)

    result = await open_add_shutter(hass, config_entry)
    assert CONF_DISCOVERED not in str(result["data_schema"].schema)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHUTTER_ID: OTHER_SHUTTER_ID, CONF_NAME: "Bedroom"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["data"][CONF_SHUTTERS]) == 2
