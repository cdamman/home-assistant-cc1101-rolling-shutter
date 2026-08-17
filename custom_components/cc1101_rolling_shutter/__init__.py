"""CC1101 Rolling Shutter integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_NAME,
    CONF_SHUTTERS,
    DOMAIN,
    cover_key,
    is_shutter_id,
)
from .hub import CC1101Hub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one config entry: a single CC1101 serial module."""
    hub = CC1101Hub(hass, entry)
    await hub.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the integration when a shutter is added/removed from the options.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and close the serial port."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: CC1101Hub | None = hass.data[DOMAIN].pop(entry.entry_id, None)
        if hub is not None:
            await hub.async_stop()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry created before shutters were addressed by radio ID.

    Version 1 stored the index hardcoded in the old firmware (``0`` to ``4``).
    The firmware no longer holds a device list, so those values cannot be
    translated into anything: the 4-byte ID has to be read off the air. Drop
    them and say so — each shutter reappears in the options as soon as one of
    its buttons is pressed on the original remote.
    """
    if entry.version >= 2:
        return True

    shutters = list(entry.options.get(CONF_SHUTTERS, []))
    kept = [s for s in shutters if is_shutter_id(cover_key(s))]
    dropped = [s for s in shutters if not is_shutter_id(cover_key(s))]

    if dropped:
        _LOGGER.warning(
            "Shutters %s used the old firmware's hardcoded index and had to be "
            "removed: shutters are now addressed by their 4-byte radio ID. "
            "Press a button on each original remote and re-add them from the "
            "integration options, where they will show up as discovered.",
            ", ".join(
                f"{s.get(CONF_NAME, '?')} ({cover_key(s) or '?'})" for s in dropped
            ),
        )

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_SHUTTERS: kept},
        version=2,
    )
    return True


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
