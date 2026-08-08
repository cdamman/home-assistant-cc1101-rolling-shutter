"""Tests for the async backend that serializes the RF transmissions."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import serial

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.cc1101_rolling_shutter.backend import SerialShutterBackend


def _backend(hass: HomeAssistant, controller: MagicMock, lock: asyncio.Lock | None = None):
    return SerialShutterBackend(hass, controller, "4", lock or asyncio.Lock())


async def test_send_forwards_the_action(hass: HomeAssistant) -> None:
    """A successful send calls the controller with the shutter ID."""
    controller = MagicMock()
    controller.send_command.return_value = "Sending"

    await _backend(hass, controller).async_send("open")

    controller.send_command.assert_called_once_with("4", "open")


async def test_unexpected_response_raises(hass: HomeAssistant) -> None:
    """A response without the expected marker is an error."""
    controller = MagicMock()
    controller.send_command.return_value = "Unknown command"

    with pytest.raises(HomeAssistantError, match="Unexpected response"):
        await _backend(hass, controller).async_send("open")


async def test_serial_failure_is_wrapped(hass: HomeAssistant) -> None:
    """A serial exception is surfaced as a HomeAssistantError."""
    controller = MagicMock()
    controller.send_command.side_effect = serial.SerialException("cable unplugged")

    with pytest.raises(HomeAssistantError, match="Serial link failure"):
        await _backend(hass, controller).async_send("close")


async def test_commands_sharing_a_lock_are_serialized(hass: HomeAssistant) -> None:
    """Two shutters on the same module never transmit at the same time."""
    in_flight = 0
    max_in_flight = 0

    def send_command(shutter_id: str, action: str) -> str:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        in_flight -= 1
        return "Sending"

    controller = MagicMock()
    controller.send_command.side_effect = send_command
    lock = asyncio.Lock()

    await asyncio.gather(
        _backend(hass, controller, lock).async_send("open"),
        _backend(hass, controller, lock).async_send("close"),
    )

    assert max_in_flight == 1
    assert controller.send_command.call_count == 2


async def test_rf_delay_is_awaited_inside_the_lock(hass: HomeAssistant) -> None:
    """The RF spacing delay runs before the lock is released."""
    controller = MagicMock()
    controller.send_command.return_value = "Sending"
    lock = asyncio.Lock()
    locked_during_delay: bool | None = None

    async def fake_sleep(delay: float) -> None:
        nonlocal locked_during_delay
        locked_during_delay = lock.locked()

    with (
        patch(
            "custom_components.cc1101_rolling_shutter.backend.RF_INTERCOMMAND_DELAY",
            0.01,
        ),
        patch(
            "custom_components.cc1101_rolling_shutter.backend.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
    ):
        sleep.side_effect = fake_sleep
        await _backend(hass, controller, lock).async_send("open")

    sleep.assert_awaited_once_with(0.01)
    assert locked_during_delay is True


async def test_no_delay_when_disabled(hass: HomeAssistant) -> None:
    """A delay of 0 skips the sleep entirely."""
    controller = MagicMock()
    controller.send_command.return_value = "Sending"

    with patch(
        "custom_components.cc1101_rolling_shutter.backend.asyncio.sleep"
    ) as sleep:
        await _backend(hass, controller).async_send("stop")

    sleep.assert_not_called()
