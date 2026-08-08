"""Tests for the blocking serial controller."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import serial

from custom_components.cc1101_rolling_shutter.const import SERIAL_TIMEOUT
from custom_components.cc1101_rolling_shutter.serial_controller import SerialController


@pytest.fixture
def serial_class() -> MagicMock:
    """Patch ``serial.Serial`` and return the class mock."""
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.serial.Serial"
    ) as serial_class:
        serial_class.return_value.is_open = True
        serial_class.return_value.readline.side_effect = [b"4 open\r\n", b"Sending\r\n"]
        yield serial_class


def test_send_command_writes_and_returns_second_line(serial_class: MagicMock) -> None:
    """The command is written and the second line is returned as response."""
    controller = SerialController("/dev/ttyUSB0", 115200)

    assert controller.send_command("4", "open") == "Sending"

    serial_class.assert_called_once_with(
        port="/dev/ttyUSB0", baudrate=115200, timeout=SERIAL_TIMEOUT
    )
    port = serial_class.return_value
    port.reset_input_buffer.assert_called_once()
    port.write.assert_called_once_with(b"4 open\n")
    port.flush.assert_called_once()


def test_port_is_opened_only_once(serial_class: MagicMock) -> None:
    """A second command reuses the already open port."""
    port = serial_class.return_value
    port.readline.side_effect = [
        b"4 open\r\n",
        b"Sending\r\n",
        b"4 close\r\n",
        b"Sending\r\n",
    ]
    controller = SerialController("/dev/ttyUSB0", 115200)

    controller.send_command("4", "open")
    controller.send_command("4", "close")

    assert serial_class.call_count == 1
    assert port.write.call_args_list[1].args == (b"4 close\n",)


def test_serial_error_closes_the_port_and_reraises(serial_class: MagicMock) -> None:
    """A serial failure closes the port so the next call reopens it."""
    port = serial_class.return_value
    port.write.side_effect = serial.SerialException("boom")
    controller = SerialController("/dev/ttyUSB0", 115200)

    with pytest.raises(serial.SerialException):
        controller.send_command("4", "open")

    port.close.assert_called_once()

    # Next call reopens a fresh port.
    port.write.side_effect = None
    port.readline.side_effect = [b"4 open\r\n", b"Sending\r\n"]
    assert controller.send_command("4", "open") == "Sending"
    assert serial_class.call_count == 2


def test_close_is_idempotent(serial_class: MagicMock) -> None:
    """Closing twice does not raise and does not close twice."""
    controller = SerialController("/dev/ttyUSB0", 115200)
    controller.send_command("4", "open")

    controller.close()
    controller.close()

    serial_class.return_value.close.assert_called_once()


def test_close_without_open_port_is_a_noop(serial_class: MagicMock) -> None:
    """Closing a controller that never opened a port does nothing."""
    SerialController("/dev/ttyUSB0", 115200).close()

    serial_class.assert_not_called()


def test_command_terminator_is_appended(serial_class: MagicMock) -> None:
    """The configured terminator ends every command."""
    with patch(
        "custom_components.cc1101_rolling_shutter.serial_controller.COMMAND_TERMINATOR",
        "",
    ):
        SerialController("/dev/ttyUSB0", 115200).send_command("7", "stop")

    serial_class.return_value.write.assert_called_once_with(b"7 stop")
