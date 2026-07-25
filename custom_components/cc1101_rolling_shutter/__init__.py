"""CC1101 Rolling Shutter integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_BAUDRATE, CONF_PORT, DOMAIN
from .serial_controller import SerialController

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one config entry (one serial port = one CC1101 module)."""
    hass.data.setdefault(DOMAIN, {})
    # The lock is shared by every shutter of the module to serialize the RF
    # transmissions (one at a time).
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": SerialController(
            port=entry.data[CONF_PORT],
            baudrate=entry.data[CONF_BAUDRATE],
        ),
        "lock": asyncio.Lock(),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and close the serial port."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data is not None:
            await hass.async_add_executor_job(data["controller"].close)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
