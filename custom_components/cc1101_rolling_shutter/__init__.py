"""CC1101 Rolling Shutter integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_SHUTTERS,
    DOMAIN,
    cover_key,
)
from .serial_controller import SerialController

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one config entry: a single CC1101 serial module."""
    hass.data.setdefault(DOMAIN, {})

    # One serial port = one CC1101 module. The lock is shared by every shutter
    # of that module to serialize the RF transmissions (one at a time).
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": SerialController(
            port=entry.data[CONF_PORT],
            baudrate=entry.data[CONF_BAUDRATE],
        ),
        "lock": asyncio.Lock(),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the integration when a shutter is added/removed from the options.
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


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting a device (a shutter) from the UI.

    Without this hook, Home Assistant refuses to delete a device provided by
    the integration. On top of allowing the deletion, we drop the matching
    shutter from the options so that it is not recreated on the next reload.
    """
    # Our device identifiers look like (DOMAIN, "<entry_id>_<key>").
    prefix = f"{config_entry.entry_id}_"
    key: str | None = None
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            key = identifier[len(prefix):]
            break

    if key is None:
        # Unknown device (should not happen): allow the deletion anyway.
        return True

    shutters = list(config_entry.options.get(CONF_SHUTTERS, []))
    remaining = [s for s in shutters if cover_key(s) != key]
    if len(remaining) != len(shutters):
        hass.config_entries.async_update_entry(
            config_entry,
            options={**config_entry.options, CONF_SHUTTERS: remaining},
        )

    return True
