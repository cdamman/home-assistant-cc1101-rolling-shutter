"""Tests for setup, unload, migration and device removal."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter import (
    async_remove_config_entry_device,
)
from custom_components.cc1101_rolling_shutter.const import (
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
)

from .conftest import (
    OTHER_SHUTTER_ID,
    TEST_BAUDRATE,
    TEST_PORT,
    TEST_SHUTTER_ID,
    FakeFirmware,
)


async def test_setup_and_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The entry starts the reader and stops it on unload."""
    await setup_entry(config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert firmware.started is True

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert config_entry.entry_id not in hass.data[DOMAIN]
    assert firmware.stopped is True


async def test_controller_uses_the_configured_port(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """The port and baud rate from the entry data reach the controller."""
    await setup_entry(config_entry)

    kwargs = firmware.controller_class.call_args.kwargs
    assert kwargs["port"] == TEST_PORT
    assert kwargs["baudrate"] == TEST_BAUDRATE


async def test_updating_options_reloads_the_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Adding a shutter through the options creates its entity."""
    await setup_entry(config_entry)

    hass.config_entries.async_update_entry(
        config_entry,
        options={
            CONF_SHUTTERS: [
                {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"},
                {CONF_SHUTTER_ID: OTHER_SHUTTER_ID, CONF_NAME: "Kitchen"},
            ]
        },
    )
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids("cover")) == 2


async def test_removing_a_device_drops_it_from_the_options(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Deleting a shutter device also removes it from the options."""
    await setup_entry(config_entry)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{config_entry.entry_id}_{TEST_SHUTTER_ID}")}
    )
    assert device is not None

    assert await async_remove_config_entry_device(hass, config_entry, device)
    await hass.async_block_till_done()

    assert config_entry.options[CONF_SHUTTERS] == []


async def test_removing_an_unknown_device_is_allowed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A device we cannot map to a shutter is still removable."""
    await setup_entry(config_entry)

    device_registry = dr.async_get(hass)
    stale = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "some-other-entry_9")},
    )

    assert await async_remove_config_entry_device(hass, config_entry, stale)

    assert len(config_entry.options[CONF_SHUTTERS]) == 1


async def test_migration_drops_legacy_index_shutters(
    hass: HomeAssistant, firmware: FakeFirmware, setup_entry
) -> None:
    """Version 1 stored the firmware's hardcoded index, which cannot be mapped.

    Those entries are removed so the shutter can be re-added by its radio ID;
    anything already in the new format is kept.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=TEST_PORT,
        data={CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE},
        options={
            CONF_SHUTTERS: [
                {CONF_SHUTTER_ID: "4", CONF_NAME: "Bedroom"},
                {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"},
            ]
        },
    )
    await setup_entry(entry)

    assert entry.version == 2
    assert entry.options[CONF_SHUTTERS] == [
        {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"}
    ]
    # Only the shutter with a real radio ID gets an entity.
    assert hass.states.async_entity_ids("cover") == ["cover.living_room"]


async def test_migration_is_a_noop_for_current_entries(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A version 2 entry is left untouched."""
    await setup_entry(config_entry)

    assert config_entry.version == 2
    assert len(config_entry.options[CONF_SHUTTERS]) == 1
