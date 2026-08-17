"""Constants for the CC1101 Rolling Shutter integration."""
from __future__ import annotations

import re

DOMAIN = "cc1101_rolling_shutter"

# Configuration keys
CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_SHUTTERS = "shutters"
CONF_SHUTTER_ID = "shutter_id"
CONF_NAME = "name"

# Defaults
DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 115200

# Serial protocol
# Terminator appended to every command. The firmware reads one command per line.
COMMAND_TERMINATOR = "\n"
# How long to wait for the firmware to confirm a command with its "tx" event.
# The firmware prints that event *after* the whole burst has gone out, so this
# has to cover the full transmission: 4 frames x 4 repetitions, ~0.5 s in
# practice. See PROTOCOL.md.
SERIAL_TIMEOUT = 5
# Read timeout of the background line reader. It only bounds how quickly the
# reader notices that the integration is unloading, so it is deliberately short
# and unrelated to SERIAL_TIMEOUT above.
READ_POLL_TIMEOUT = 0.5
# Delay before the port is reopened after a serial failure.
RECONNECT_DELAY = 5

# Events emitted by the firmware, one JSON object per line.
EVENT_READY = "ready"
EVENT_TX = "tx"
EVENT_RX = "rx"
EVENT_ERROR = "error"
EVENT_STATUS = "status"
EVENT_RAW = "raw"

# Commands understood by the firmware.
ACTION_OPEN = "open"
ACTION_CLOSE = "close"
ACTION_STOP = "stop"

# Dispatcher signals
SIGNAL_SHUTTER_EVENT = f"{DOMAIN}_shutter_event_{{}}_{{}}"
SIGNAL_DISCOVERY = f"{DOMAIN}_discovery_{{}}"

# A shutter is addressed by its 4-byte radio identifier, written as 8 hex
# digits. Separators are accepted on input and stripped.
_ID_SEPARATORS = re.compile(r"[\s:.\-]")
_ID_PATTERN = re.compile(r"\A[0-9a-f]{8}\Z")


def normalise_shutter_id(value: str) -> str:
    """Return the canonical form of a shutter ID: 8 lowercase hex digits.

    Accepts the separators the firmware accepts, so ``12:34:56:00`` and
    ``12345600`` are the same shutter. Raises ``ValueError`` otherwise.
    """
    cleaned = _ID_SEPARATORS.sub("", str(value)).lower()
    if not _ID_PATTERN.match(cleaned):
        raise ValueError(f"invalid shutter id: {value!r}")
    return cleaned


def is_shutter_id(value: str) -> bool:
    """Return whether ``value`` is a usable shutter ID."""
    try:
        normalise_shutter_id(value)
    except ValueError:
        return False
    return True


def cover_key(item: dict[str, str]) -> str:
    """Return the key (radio ID) of a shutter.

    Used to deduplicate, look up and delete a shutter in the options.
    """
    return item.get(CONF_SHUTTER_ID, "")
