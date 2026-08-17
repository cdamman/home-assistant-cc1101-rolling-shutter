"""Serial link to the CC1101 firmware.

The firmware is event driven: it accepts one command per line, and reports
everything it does — and everything it hears on the air — as JSON objects, one
per line. So the port cannot be driven request/response any more. This module
owns a background thread that reads lines continuously and hands each decoded
event to a callback, plus a writer used to send commands.

Both the reader thread and ``send_command`` are blocking; the callback is
therefore invoked from the reader thread and must not touch Home Assistant
directly. ``CC1101Hub`` is responsible for hopping back onto the event loop.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import serial

from .const import (
    COMMAND_TERMINATOR,
    READ_POLL_TIMEOUT,
    RECONNECT_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class SerialController:
    """Own the serial port: a background line reader plus a writer."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        on_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._on_event = on_event
        self._serial: serial.Serial | None = None
        # Guards the port against a write landing while the reader reopens it.
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Start the reader thread. It opens the port and keeps it open."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"cc1101-{self._port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the reader thread and close the port.

        The thread is joined *before* the port is closed, and closes it itself
        on the way out. Closing it from here first would pull the file
        descriptor out from under a read already in flight: pyserial sets
        ``fd = None`` in ``close()``, and the reader is by then past the
        ``is_open`` check, so ``os.read(None, ...)`` raises TypeError.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            # The reader wakes at most READ_POLL_TIMEOUT after the flag is set.
            thread.join(timeout=READ_POLL_TIMEOUT * 4)
        # Fallback: close here if the reader never started, or failed to exit.
        with self._lock:
            self._close_locked()

    # -- writing -----------------------------------------------------------
    def send_command(self, shutter_id: str, action: str) -> None:
        """Write ``<id> <action>`` to the firmware.

        Does not wait for a reply: the firmware answers asynchronously with a
        ``tx`` event, which the hub correlates. Raises ``serial.SerialException``
        if the port is unusable.
        """
        line = f"{shutter_id} {action}{COMMAND_TERMINATOR}"
        with self._lock:
            if self._serial is None or not self._serial.is_open:
                raise serial.SerialException(f"port {self._port} is not open")
            _LOGGER.debug("Sending %r", line.strip())
            self._serial.write(line.encode("ascii"))
            self._serial.flush()

    # -- reading -----------------------------------------------------------
    def _open_locked(self) -> None:
        """Open the port (called under the lock)."""
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=READ_POLL_TIMEOUT,
        )
        _LOGGER.debug("Opened %s @ %d baud", self._port, self._baudrate)

    def _close_locked(self) -> None:
        """Close the port (called under the lock)."""
        if self._serial is not None:
            try:
                self._serial.close()
            except serial.SerialException:  # pragma: no cover - best effort
                pass
        self._serial = None

    def _read_loop(self) -> None:
        """Read lines until stopped, reopening the port after a failure."""
        failures = 0
        try:
            while not self._stop.is_set():
                try:
                    with self._lock:
                        if self._serial is None or not self._serial.is_open:
                            self._open_locked()
                        port = self._serial
                    # readline() is called outside the lock so that a command
                    # can be written while the reader is blocked waiting for
                    # data.
                    raw = port.readline()
                # Anything at all: this thread must outlive it. Unplugging the
                # adapter mid-read does not always surface as SerialException —
                # pyserial can raise TypeError once the descriptor is gone.
                except Exception as err:  # noqa: BLE001
                    if self._stop.is_set():
                        break
                    failures += 1
                    # Only the first failure of a run is an error; a module
                    # left unplugged would otherwise fill the log forever.
                    log = _LOGGER.error if failures == 1 else _LOGGER.debug
                    log(
                        "Serial error on %s (retry %d in %ss): %s",
                        self._port,
                        failures,
                        RECONNECT_DELAY,
                        err,
                    )
                    with self._lock:
                        self._close_locked()
                    # Wait before retrying, but wake immediately when stopping.
                    self._stop.wait(RECONNECT_DELAY)
                    continue

                if failures:
                    _LOGGER.info("Serial link to %s restored", self._port)
                    failures = 0
                if not raw:
                    continue  # read timeout, nothing to do
                self._handle_line(raw)
        finally:
            # Own the port for the whole life of the thread, so nothing else
            # has to close it while a read might be in flight.
            with self._lock:
                self._close_locked()

    def _handle_line(self, raw: bytes) -> None:
        """Decode one line and forward it as an event."""
        line = raw.decode("ascii", errors="ignore").strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except ValueError:
            # The firmware prints a couple of plain lines at boot ("Connection
            # OK"), and noise on the wire is not worth an error.
            _LOGGER.debug("Ignoring non-JSON line: %r", line)
            return
        if not isinstance(event, dict):
            _LOGGER.debug("Ignoring non-object JSON line: %r", line)
            return
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001 - never let the reader thread die
            _LOGGER.exception("Error while handling event %s", event)
