"""Shared fixtures for the CC1101 Rolling Shutter tests."""
from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cc1101_rolling_shutter.const import (
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DOMAIN,
)

TEST_PORT = "/dev/ttyUSB0"
TEST_BAUDRATE = 115200
TEST_SHUTTER_ID = "12345600"
TEST_SHUTTER_NAME = "Living room"
OTHER_SHUTTER_ID = "0a1b2c01"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the integration from ``custom_components/``."""
    return enable_custom_integrations


class FakeFirmware:
    """Stands in for the serial controller and the firmware behind it.

    Records the commands written, and lets a test push JSON events back the way
    the reader thread would. By default it acknowledges every command with the
    ``tx`` event the firmware sends once a burst has been transmitted.
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.started = False
        self.stopped = False
        self.auto_ack = True
        self.fail_with: Exception | None = None
        self._on_event: Callable[[dict[str, Any]], None] | None = None

    # -- the SerialController interface the hub uses --------------------
    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def send_command(self, shutter_id: str, action: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.commands.append((shutter_id, action))
        if self.auto_ack:
            self.emit({"event": "tx", "id": shutter_id, "cmd": action, "counter": 1})

    # -- test-side helpers ----------------------------------------------
    def emit(self, event: dict[str, Any]) -> None:
        """Deliver an event as the reader thread would."""
        assert self._on_event is not None, "controller was never constructed"
        self._on_event(event)

    def emit_rx(self, shutter_id: str, command: str, **extra: Any) -> None:
        """Deliver a frame heard on the air."""
        self.emit(
            {
                "event": "rx",
                "id": shutter_id,
                "cmd": command,
                "counter": 42,
                "rssi": -60,
                **extra,
            }
        )

    @property
    def last_command(self) -> tuple[str, str]:
        return self.commands[-1]


@pytest.fixture
def firmware() -> Generator[FakeFirmware]:
    """Replace SerialController with a fake, event-driven firmware."""
    fake = FakeFirmware()

    def _factory(port: str, baudrate: int, on_event) -> FakeFirmware:
        fake._on_event = on_event
        return fake

    with patch(
        "custom_components.cc1101_rolling_shutter.hub.SerialController",
        side_effect=_factory,
    ) as controller_class:
        fake.controller_class = controller_class  # type: ignore[attr-defined]
        yield fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry with a single shutter declared."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"CC1101 ({TEST_PORT})",
        unique_id=TEST_PORT,
        version=2,
        data={CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE},
        options={
            CONF_SHUTTERS: [
                {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: TEST_SHUTTER_NAME}
            ]
        },
    )


@pytest.fixture
def setup_entry(hass, firmware: FakeFirmware):
    """Return a coroutine that sets a config entry up and waits for it."""

    async def _setup(entry: MockConfigEntry) -> None:
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return _setup
