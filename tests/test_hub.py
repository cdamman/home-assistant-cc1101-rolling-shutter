"""Tests for the hub: command acknowledgement, air events and discovery."""
from __future__ import annotations

import asyncio

import pytest
import serial

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter.const import DOMAIN

from .conftest import OTHER_SHUTTER_ID, TEST_SHUTTER_ID, FakeFirmware


def get_hub(hass: HomeAssistant, entry: MockConfigEntry):
    return hass.data[DOMAIN][entry.entry_id]


async def test_send_waits_for_the_firmware_acknowledgement(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A command resolves once the firmware reports its ``tx`` event."""
    await setup_entry(config_entry)

    await get_hub(hass, config_entry).async_send(TEST_SHUTTER_ID, "open")

    assert firmware.last_command == (TEST_SHUTTER_ID, "open")


async def test_send_times_out_without_an_acknowledgement(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A silent firmware surfaces as an error rather than hanging forever."""
    await setup_entry(config_entry)
    firmware.auto_ack = False

    with (
        patch_timeout(0.01),
        pytest.raises(HomeAssistantError, match="Timed out"),
    ):
        await get_hub(hass, config_entry).async_send(TEST_SHUTTER_ID, "open")


async def test_firmware_error_event_fails_the_command(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """An ``error`` event rejects the command in flight."""
    await setup_entry(config_entry)
    firmware.auto_ack = False
    hub = get_hub(hass, config_entry)

    async def reject_soon() -> None:
        await asyncio.sleep(0)
        firmware.emit(
            {"event": "error", "reason": "bad id", "input": TEST_SHUTTER_ID}
        )

    task = hass.async_create_task(reject_soon())
    with pytest.raises(HomeAssistantError, match="rejected"):
        await hub.async_send(TEST_SHUTTER_ID, "open")
    await task


async def test_write_failure_is_wrapped(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A serial exception surfaces as a HomeAssistantError."""
    await setup_entry(config_entry)
    firmware.fail_with = serial.SerialException("port gone")

    with pytest.raises(HomeAssistantError, match="Serial link failure"):
        await get_hub(hass, config_entry).async_send(TEST_SHUTTER_ID, "open")


async def test_commands_are_serialised(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Two shutters never transmit at once: the burst must finish first."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)
    in_flight = 0
    peak = 0
    original = firmware.send_command

    def counting_send(shutter_id: str, action: str) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        original(shutter_id, action)
        in_flight -= 1

    firmware.send_command = counting_send  # type: ignore[method-assign]

    await asyncio.gather(
        hub.async_send(TEST_SHUTTER_ID, "open"),
        hub.async_send(OTHER_SHUTTER_ID, "close"),
    )

    assert peak == 1
    assert len(firmware.commands) == 2


async def test_rx_for_a_configured_shutter_is_not_a_discovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """A configured shutter feeds its entity, not the discovery list."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)

    firmware.emit_rx(TEST_SHUTTER_ID, "open")
    await hass.async_block_till_done()

    assert hub.discovered == {}
    assert hub.available_discoveries() == []


async def test_unknown_shutter_is_discovered(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """An unconfigured shutter heard on the air becomes available to add."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)

    firmware.emit_rx(OTHER_SHUTTER_ID, "close")
    await hass.async_block_till_done()

    discoveries = hub.available_discoveries()
    assert [d.shutter_id for d in discoveries] == [OTHER_SHUTTER_ID]
    assert discoveries[0].last_command == "close"
    assert discoveries[0].rssi == -60


async def test_discovery_normalises_the_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Separators and case from the air do not create duplicates."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)

    firmware.emit_rx("0A:1B:2C:01", "open")
    firmware.emit_rx("0a1b2c01", "close")
    await hass.async_block_till_done()

    assert list(hub.discovered) == [OTHER_SHUTTER_ID]


async def test_malformed_rx_is_ignored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """Events without a usable ID never reach the discovery list."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)

    firmware.emit({"event": "rx", "cmd": "open"})
    firmware.emit({"event": "rx", "id": "nope", "cmd": "open"})
    await hass.async_block_till_done()

    assert hub.discovered == {}


async def test_informational_events_are_harmless(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    firmware: FakeFirmware,
    setup_entry,
) -> None:
    """ready / status / raw are logged and dropped."""
    await setup_entry(config_entry)
    hub = get_hub(hass, config_entry)

    firmware.emit({"event": "ready"})
    firmware.emit({"event": "status", "devices": []})
    firmware.emit({"event": "raw", "rssi": -80, "data": "deadbeef"})
    await hass.async_block_till_done()

    assert hub.discovered == {}


def patch_timeout(value: float):
    """Shrink the acknowledgement timeout for a test."""
    from unittest.mock import patch

    return patch(
        "custom_components.cc1101_rolling_shutter.hub.SERIAL_TIMEOUT", value
    )
