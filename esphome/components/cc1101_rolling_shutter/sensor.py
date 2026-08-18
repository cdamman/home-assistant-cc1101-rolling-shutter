"""Diagnostics for one shutter: its rolling counter and the remote's RSSI.

Neither says anything about where the shutter is, so both are diagnostics. The
counter follows both our own transmissions and the frames heard on the air; the
signal level only ever comes from the air, since transmitting reports none.

Declaring them here means naming the shutter twice, once for its cover and once
again for this block. The same two keys are accepted directly on the cover,
which is the shorter way round; this platform is what remains for a shutter
that has no cover — one you only ever listen to.
"""
import esphome.codegen as cg
import esphome.config_validation as cv

from . import (
    CONF_CC1101_ROLLING_SHUTTER_ID,
    CONF_ROLLING_COUNTER,
    CONF_SHUTTER_ID,
    CONF_SIGNAL_STRENGTH,
    CC1101RollingShutter,
    DIAGNOSTIC_SCHEMA,
    register_diagnostics,
    shutter_key,
)

DEPENDENCIES = ["cc1101_rolling_shutter"]

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_CC1101_ROLLING_SHUTTER_ID): cv.use_id(CC1101RollingShutter),
        cv.Required(CONF_SHUTTER_ID): shutter_key,
        **DIAGNOSTIC_SCHEMA,
    }
).add_extra(cv.has_at_least_one_key(CONF_ROLLING_COUNTER, CONF_SIGNAL_STRENGTH))


async def to_code(config):
    parent = await cg.get_variable(config[CONF_CC1101_ROLLING_SHUTTER_ID])
    await register_diagnostics(config, parent, config[CONF_SHUTTER_ID])
