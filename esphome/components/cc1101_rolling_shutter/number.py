"""The receive threshold, as something you can turn from Home Assistant.

`rssi_threshold` on the hub sets where the node starts; this makes it
adjustable while it runs, which is the only practical way to find the value
that separates a remote two rooms away from the noise in your walls.
"""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import number
from esphome.const import (
    CONF_RESTORE_VALUE,
    ENTITY_CATEGORY_CONFIG,
    UNIT_DECIBEL_MILLIWATT,
)

from . import (
    CONF_CC1101_ROLLING_SHUTTER_ID,
    CC1101RollingShutter,
    cc1101_rolling_shutter_ns,
)

DEPENDENCIES = ["cc1101_rolling_shutter"]

RssiThresholdNumber = cc1101_rolling_shutter_ns.class_(
    "RssiThresholdNumber", number.Number, cg.Component
)

CONFIG_SCHEMA = (
    number.number_schema(
        RssiThresholdNumber,
        unit_of_measurement=UNIT_DECIBEL_MILLIWATT,
        icon="mdi:signal-distance-variant",
        entity_category=ENTITY_CATEGORY_CONFIG,
    )
    .extend(
        {
            cv.GenerateID(CONF_CC1101_ROLLING_SHUTTER_ID): cv.use_id(CC1101RollingShutter),
            # A threshold found by trial deserves to outlive a reboot. On the
            # ESP8266 that wants `restore_from_flash: true` on the node to
            # survive losing power as well.
            cv.Optional(CONF_RESTORE_VALUE, default=True): cv.boolean,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_CC1101_ROLLING_SHUTTER_ID])
    # The whole usable range of the CC1101's reading: -128 dBm is below any
    # noise floor, which is to say "take everything", and 0 is deafening.
    var = await number.new_number(config, min_value=-128, max_value=0, step=1)
    await cg.register_component(var, config)
    cg.add(var.set_parent(parent))
    cg.add(var.set_restore(config[CONF_RESTORE_VALUE]))
