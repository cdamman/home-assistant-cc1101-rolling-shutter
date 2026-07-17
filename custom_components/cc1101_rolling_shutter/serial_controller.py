"""Serial link management for the CC1101 module.

The serial port is shared by every shutter of a single config entry. All
writes are serialized by a lock so that two commands sent at the same time
cannot interleave. The calls are blocking: they must be run through
``hass.async_add_executor_job`` and never directly on the asyncio loop.
"""
from __future__ import annotations

import logging
import threading

import serial

from .const import COMMAND_TERMINATOR, SERIAL_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class SerialController:
    """Open the serial port on demand and send the shutter commands."""

    def __init__(self, port: str, baudrate: int) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None
        self._lock = threading.Lock()

    def _ensure_open(self) -> None:
        """Open the port if it is not open yet (called under the lock)."""
        if self._serial is None or not self._serial.is_open:
            _LOGGER.debug("Opening port %s @ %d baud", self._port, self._baudrate)
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=SERIAL_TIMEOUT,
            )

    def _close_locked(self) -> None:
        """Close the port (called under the lock)."""
        if self._serial is not None and self._serial.is_open:
            try:
                self._serial.close()
            except serial.SerialException:  # pragma: no cover - best effort
                pass
        self._serial = None

    def send_command(self, shutter_id: str, action: str) -> str:
        """Send ``<id> <action>`` and return the module response.

        Concrete example: ``send_command("4", "open")`` writes ``4 open\\n``
        to the port and returns the response line (``Sending`` on success).
        Raises ``serial.SerialException`` on a link error.
        """
        command = f"{shutter_id} {action}{COMMAND_TERMINATOR}"
        with self._lock:
            try:
                self._ensure_open()
                assert self._serial is not None
                # Flush the input buffer so we do not read a stale response.
                self._serial.reset_input_buffer()
                self._serial.write(command.encode("ascii"))
                self._serial.flush()
                # The module returns two lines: the first one echoes the
                # command that was sent, the second one is the actual response
                # (e.g. "Sending").
                echo = self._serial.readline().decode("ascii", errors="ignore").strip()
                raw = self._serial.readline()
                response = raw.decode("ascii", errors="ignore").strip()
                _LOGGER.debug(
                    "Command %r sent, echo %r, response %r",
                    command.strip(),
                    echo,
                    response,
                )
                return response
            except serial.SerialException as err:
                # On a link failure, close the port so that the next call
                # reopens it cleanly.
                _LOGGER.error("Serial error (%s): %s", self._port, err)
                self._close_locked()
                raise

    def close(self) -> None:
        """Close the port cleanly (called when the integration is unloaded)."""
        with self._lock:
            self._close_locked()
