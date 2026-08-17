"""Tests for the background line reader that talks to the firmware."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any
from unittest.mock import patch

import pytest
import serial

from custom_components.cc1101_rolling_shutter.const import READ_POLL_TIMEOUT
from custom_components.cc1101_rolling_shutter.serial_controller import SerialController


class FakeSerial:
    """A serial port that replays queued lines, then idles like a real one."""

    def __init__(self, lines: list[bytes] | None = None) -> None:
        self._lines = deque(lines or [])
        self.is_open = True
        self.fd = 3
        self.written: list[bytes] = []
        self.closed = 0
        self.fail_readline: Exception | None = None
        self.reading = False
        self.closed_mid_read = False

    def readline(self) -> bytes:
        if self.fail_readline is not None:
            err, self.fail_readline = self.fail_readline, None
            raise err
        if self._lines:
            return self._lines.popleft()
        self.reading = True
        try:
            for _ in range(4):
                time.sleep(0.005)  # stand in for the read timeout
                if self.fd is None:
                    # Exactly what pyserial does once close() has dropped the
                    # descriptor: os.read(None, ...) raises TypeError.
                    raise TypeError(
                        "'NoneType' object cannot be interpreted as an integer"
                    )
            return b""
        finally:
            self.reading = False

    def feed(self, line: bytes) -> None:
        self._lines.append(line)

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if self.reading:
            self.closed_mid_read = True
        self.is_open = False
        self.fd = None
        self.closed += 1


def wait_for(predicate, timeout: float = 2.0) -> None:
    """Spin until the reader thread has caught up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met before timeout")


@pytest.fixture
def collected() -> list[dict[str, Any]]:
    return []


def make_controller(collected: list, port: FakeSerial) -> SerialController:
    controller = SerialController("/dev/ttyUSB0", 115200, collected.append)
    return controller


def test_json_lines_become_events(collected: list) -> None:
    """Each JSON line is decoded and handed to the callback."""
    port = FakeSerial(
        [
            b'{"event":"ready"}\n',
            b'{"event":"rx","id":"12345600","cmd":"open","rssi":-60}\n',
        ]
    )
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
        return_value=port,
    ):
        controller = make_controller(collected, port)
        controller.start()
        try:
            wait_for(lambda: len(collected) == 2)
        finally:
            controller.stop()

    assert collected[0] == {"event": "ready"}
    assert collected[1]["id"] == "12345600"
    assert collected[1]["cmd"] == "open"


def test_non_json_and_blank_lines_are_ignored(collected: list) -> None:
    """The firmware prints plain text at boot; noise must not raise."""
    port = FakeSerial(
        [
            b"Connection OK\n",
            b"\n",
            b"[not json\n",
            b'"a bare string"\n',
            b'{"event":"ready"}\n',
        ]
    )
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
        return_value=port,
    ):
        controller = make_controller(collected, port)
        controller.start()
        try:
            wait_for(lambda: collected == [{"event": "ready"}])
        finally:
            controller.stop()


def test_send_command_writes_a_line(collected: list) -> None:
    """A command is written as ``<id> <action>`` terminated by a newline."""
    port = FakeSerial()
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
        return_value=port,
    ):
        controller = make_controller(collected, port)
        controller.start()
        try:
            wait_for(lambda: port.is_open)
            controller.send_command("12345600", "open")
        finally:
            controller.stop()

    assert port.written == [b"12345600 open\n"]


def test_send_command_without_a_port_raises(collected: list) -> None:
    """Writing before the port is open is an error, not a silent no-op."""
    controller = SerialController("/dev/ttyUSB0", 115200, collected.append)
    with pytest.raises(serial.SerialException):
        controller.send_command("12345600", "open")


def test_reader_reconnects_after_a_failure(collected: list) -> None:
    """A serial error closes the port; the reader reopens it and carries on."""
    first = FakeSerial()
    first.fail_readline = serial.SerialException("cable unplugged")
    second = FakeSerial([b'{"event":"ready"}\n'])
    ports = deque([first, second])

    with (
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
            side_effect=lambda **_: ports.popleft(),
        ),
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller."
            "RECONNECT_DELAY",
            0.01,
        ),
    ):
        controller = SerialController("/dev/ttyUSB0", 115200, collected.append)
        controller.start()
        try:
            wait_for(lambda: collected == [{"event": "ready"}])
        finally:
            controller.stop()

    assert first.closed >= 1


def test_a_failing_callback_does_not_kill_the_reader(collected: list) -> None:
    """One bad event must not stop the stream."""
    seen: list[dict] = []

    def callback(event: dict) -> None:
        if event.get("event") == "boom":
            raise RuntimeError("handler exploded")
        seen.append(event)

    port = FakeSerial([b'{"event":"boom"}\n', b'{"event":"ready"}\n'])
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
        return_value=port,
    ):
        controller = SerialController("/dev/ttyUSB0", 115200, callback)
        controller.start()
        try:
            wait_for(lambda: seen == [{"event": "ready"}])
        finally:
            controller.stop()


def test_stop_closes_the_port_and_joins_the_thread(collected: list) -> None:
    """Unloading leaves no thread behind."""
    port = FakeSerial()
    before = threading.active_count()
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
        return_value=port,
    ):
        controller = make_controller(collected, port)
        controller.start()
        wait_for(lambda: threading.active_count() > before)
        controller.stop()

    assert port.closed >= 1
    wait_for(lambda: threading.active_count() == before, timeout=READ_POLL_TIMEOUT * 8)


def test_stop_never_closes_the_port_under_a_live_read(collected: list) -> None:
    """Regression: closing mid-read killed the reader thread.

    pyserial drops the descriptor in close(), and a read already past the
    is_open check then raises TypeError — which is not a SerialException, so it
    escaped and Home Assistant logged "Uncaught thread exception". stop() now
    joins the reader first and lets it close the port itself.
    """
    port = FakeSerial()
    escaped: list[str] = []
    previous_hook = threading.excepthook
    threading.excepthook = lambda args: escaped.append(args.exc_type.__name__)
    try:
        with patch(
            "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
            return_value=port,
        ):
            controller = make_controller(collected, port)
            controller.start()
            wait_for(lambda: port.reading)  # blocked inside readline()
            controller.stop()
    finally:
        threading.excepthook = previous_hook

    assert escaped == []
    assert port.closed_mid_read is False
    assert port.closed >= 1


def test_reader_survives_an_unexpected_exception(collected: list) -> None:
    """Any exception is recoverable, not just SerialException."""
    first = FakeSerial()
    first.fail_readline = TypeError("descriptor went away")
    second = FakeSerial([b'{"event":"ready"}\n'])
    ports = deque([first, second])

    with (
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
            side_effect=lambda **_: ports.popleft(),
        ),
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller."
            "RECONNECT_DELAY",
            0.01,
        ),
    ):
        controller = SerialController("/dev/ttyUSB0", 115200, collected.append)
        controller.start()
        try:
            wait_for(lambda: collected == [{"event": "ready"}])
        finally:
            controller.stop()


def test_repeated_failures_log_once(collected: list, caplog) -> None:
    """A module left unplugged must not fill the log with one error per retry."""
    port = FakeSerial()
    port.fail_readline = serial.SerialException("unplugged")

    def always_fail() -> bytes:
        raise serial.SerialException("unplugged")

    port.readline = always_fail  # type: ignore[method-assign]

    with (
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial",
            return_value=port,
        ),
        patch(
            "custom_components.cc1101_rolling_shutter.serial_controller."
            "RECONNECT_DELAY",
            0.01,
        ),
        caplog.at_level("ERROR"),
    ):
        controller = SerialController("/dev/ttyUSB0", 115200, collected.append)
        controller.start()
        try:
            time.sleep(0.15)  # several retries
        finally:
            controller.stop()

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1, f"expected one error, got {len(errors)}"
