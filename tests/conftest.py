"""Shared fixtures for the CC1101 Rolling Shutter tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

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
TEST_SHUTTER_ID = "4"
TEST_SHUTTER_NAME = "Living room"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the integration from ``custom_components/``."""
    return enable_custom_integrations


@pytest.fixture(autouse=True)
def no_rf_delay() -> Generator[None]:
    """Remove the RF spacing delay so tests do not sleep for real."""
    with patch(
        "custom_components.cc1101_rolling_shutter.backend.RF_INTERCOMMAND_DELAY", 0
    ):
        yield


@pytest.fixture
def mock_controller_class() -> Generator[MagicMock]:
    """Replace the serial controller class with a mock that always succeeds."""
    with patch(
        "custom_components.cc1101_rolling_shutter.SerialController", autospec=True
    ) as controller_class:
        controller_class.return_value.send_command.return_value = "Sending"
        yield controller_class


@pytest.fixture
def mock_controller(mock_controller_class: MagicMock) -> MagicMock:
    """Return the serial controller instance the integration will use."""
    return mock_controller_class.return_value


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry with a single shutter declared."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"CC1101 ({TEST_PORT})",
        unique_id=TEST_PORT,
        data={CONF_PORT: TEST_PORT, CONF_BAUDRATE: TEST_BAUDRATE},
        options={
            CONF_SHUTTERS: [
                {CONF_SHUTTER_ID: TEST_SHUTTER_ID, CONF_NAME: TEST_SHUTTER_NAME}
            ]
        },
    )
