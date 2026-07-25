"""Sending commands to the CC1101 module over the serial link.

Every command for a given CC1101 module goes through a shared
``asyncio.Lock``: only one transmission is in flight at a time (FIFO order,
without tying up several executor threads). A short delay after each send
spaces out the radio transmissions to avoid RF collisions. ``async_send``
raises ``HomeAssistantError`` on failure, which lets the entity roll back its
optimistic state.
"""
from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import EXPECTED_RESPONSE, RF_INTERCOMMAND_DELAY
from .serial_controller import SerialController


class SerialShutterBackend:
    """Drive a CC1101 shutter through its radio ID."""

    def __init__(
        self,
        hass: HomeAssistant,
        controller: SerialController,
        shutter_id: str,
        lock: asyncio.Lock,
    ) -> None:
        self._hass = hass
        self._controller = controller
        self._shutter_id = shutter_id
        # Lock shared by every shutter of the same module (same CC1101).
        self._lock = lock

    async def async_send(self, action: str) -> None:
        """Send ``action`` (``"open"`` / ``"close"`` / ``"stop"``)."""
        # Serialize the sends: the next command waits here until the previous
        # one (transmission + RF spacing) is done.
        async with self._lock:
            try:
                response = await self._hass.async_add_executor_job(
                    self._controller.send_command, self._shutter_id, action
                )
            except Exception as err:  # noqa: BLE001 - surfaced as a HA error
                raise HomeAssistantError(
                    f"Serial link failure for shutter {self._shutter_id}: {err}"
                ) from err

            if EXPECTED_RESPONSE not in response:
                raise HomeAssistantError(
                    f"Unexpected response from shutter {self._shutter_id} "
                    f"(expected {EXPECTED_RESPONSE!r}, got {response!r})"
                )

            # Let the RF transmission finish before releasing the lock (and
            # therefore before allowing the next command).
            if RF_INTERCOMMAND_DELAY > 0:
                await asyncio.sleep(RF_INTERCOMMAND_DELAY)
