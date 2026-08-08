"""Tests for the setup, unload and device removal of a config entry."""
from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter import (
    async_remove_config_entry_device,
)
from custom_components.cc1101_rolling_shutter.const import (
    CONF_NAME,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
)

from .conftest import TEST_BAUDRATE, TEST_PORT, TEST_SHUTTER_ID


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """The entry sets up, opens a controller, then unloads and closes it."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][config_entry.entry_id]["controller"] is mock_controller

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert config_entry.entry_id not in hass.data[DOMAIN]
    mock_controller.close.assert_called_once()


async def test_controller_uses_the_configured_port(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_controller_class: MagicMock,
) -> None:
    """The port and baud rate from the entry data reach the controller."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_controller_class.assert_called_once_with(
        port=TEST_PORT, baudrate=TEST_BAUDRATE
    )


async def test_updating_options_reloads_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Adding a shutter through the options creates its entity."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        config_entry,
        options={
            CONF_SHUTTERS: [
                {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: "Living room"},
                {CONF_SHUTTER_ID: "5", CONF_NAME: "Kitchen"},
            ]
        },
    )
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids("cover")) == 2


async def test_removing_a_device_drops_it_from_the_options(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """Deleting a shutter device also removes it from the options."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{config_entry.entry_id}_{TEST_SHUTTER_ID}")}
    )
    assert device is not None

    assert await async_remove_config_entry_device(hass, config_entry, device)
    await hass.async_block_till_done()

    assert config_entry.options[CONF_SHUTTERS] == []


async def test_removing_an_unknown_device_is_allowed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_controller: MagicMock
) -> None:
    """A device we cannot map to a shutter is still removable."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    stale = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "some-other-entry_9")},
    )

    assert await async_remove_config_entry_device(hass, config_entry, stale)

    # The declared shutter is untouched.
    assert len(config_entry.options[CONF_SHUTTERS]) == 1
