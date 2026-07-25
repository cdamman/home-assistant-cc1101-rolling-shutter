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

# Spacing delay between two consecutive RF transmissions on the same CC1101
# module, in seconds. The module acknowledges with "Sending" at the START of
# the transmission; this delay lets the radio transmission finish before the
# next command is sent, avoiding RF collisions when several shutters are
# operated at the same time. Set to 0 if your module already blocks until the
# transmission is complete.
RF_INTERCOMMAND_DELAY = 0.4
