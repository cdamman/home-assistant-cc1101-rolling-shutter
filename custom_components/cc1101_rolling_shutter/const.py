"""Constants for the CC1101 Rolling Shutter integration."""
from __future__ import annotations

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
# Terminator appended to every command. Most firmwares expect a newline.
# Set to "" if your module does not need one.
COMMAND_TERMINATOR = "\n"
# Response the module returns once the command has been sent out.
EXPECTED_RESPONSE = "Sending"
# Response read timeout, in seconds.
SERIAL_TIMEOUT = 2
