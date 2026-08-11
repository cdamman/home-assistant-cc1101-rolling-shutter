"""Constants for the CC1101 Rolling Shutter integration."""
from __future__ import annotations

DOMAIN = "cc1101_rolling_shutter"

# Configuration keys
CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_SHUTTERS = "shutters"
CONF_SHUTTER_ID = "shutter_id"
CONF_NAME = "name"


def cover_key(item: dict[str, str]) -> str:
    """Return the key (radio ID) of a shutter.

    Used to deduplicate, look up and delete a shutter in the options.
    """
    return item.get(CONF_SHUTTER_ID, "")


# Defaults
DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 115200

# Serial protocol
# Terminator appended to every command. Most firmwares expect a newline.
# Set to "" if your module does not need one.
COMMAND_TERMINATOR = "\n"
# Response the module returns once the command has been sent out.
EXPECTED_RESPONSE = "Sending"
# Response read timeout, in seconds. It applies to each read, and a command
# reads two lines (the echo, then the response), so a fully unresponsive module
# blocks an executor thread for up to twice this.
SERIAL_TIMEOUT = 5

# Spacing delay between two consecutive RF transmissions on the same CC1101
# module, in seconds. The module acknowledges with "Sending" at the START of
# the transmission; this delay lets the radio transmission finish before the
# next command is sent, avoiding RF collisions when several shutters are
# operated at the same time.
#
# Sized from the firmware in firmware/: one command is NB_SIGNALS (4) frames
# repeated NB_RETRIES (4) times, and each frame is followed by a 32 ms gap, so
# the radio stays busy for at least ~0.5 s after the acknowledgement. 0.8 s
# leaves margin on top of that. Set to 0 if your module blocks until the
# transmission is complete instead of acknowledging up front.
RF_INTERCOMMAND_DELAY = 0.8
