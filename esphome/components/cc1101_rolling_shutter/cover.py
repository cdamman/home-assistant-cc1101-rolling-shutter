"""One cover per shutter, addressed by its 4-byte radio id.

The two per-shutter diagnostics can be declared right here, which is the point:
the id and the name are already written for the cover, and repeating both in a
`sensor:` block to get a counter is a lot of typing for one number. Written
bare, each diagnostic takes its name from the cover's.
"""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import final_validate as fv
from esphome.components import cover
from esphome.const import DEVICE_CLASS_SHUTTER

from . import (
    CONF_CC1101_ROLLING_SHUTTER_ID,
    CONF_SHUTTER_ID,
    CC1101RollingShutter,
    DEFERRED_DIAGNOSTIC_SCHEMA,
    apply_diagnostic_labels,
    cc1101_rolling_shutter_ns,
    register_diagnostics,
    validate_inherited_diagnostics,
    shutter_key,
)

DEPENDENCIES = ["cc1101_rolling_shutter"]

CC1101RollingShutterCover = cc1101_rolling_shutter_ns.class_(
    "CC1101RollingShutterCover", cover.Cover, cg.Component
)

CONFIG_SCHEMA = (
    # Both diagnostics are wanted on every shutter, so they are the defaults
    # rather than lines to repeat per shutter. Any of them can still be written
    # to override it, and `internal: true` keeps one out of Home Assistant.
    #
    # `shutter` rather than `blind`: it is what these are, and it is what makes
    # Home Assistant draw them as roller shutters that follow the state — a
    # device class is the only thing per-state icons come from. See the README
    # for what it costs in Google Home.
    cover.cover_schema(CC1101RollingShutterCover, device_class=DEVICE_CLASS_SHUTTER)
    .extend(
        {
            cv.GenerateID(CONF_CC1101_ROLLING_SHUTTER_ID): cv.use_id(CC1101RollingShutter),
            cv.Required(CONF_SHUTTER_ID): shutter_key,
            **DEFERRED_DIAGNOSTIC_SCHEMA,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .add_extra(validate_inherited_diagnostics)
)


def _final_validate(config):
    """Apply the hub's diagnostic labels, which are only readable from here."""
    full = fv.full_config.get()
    hub_path = full.get_path_for_id(config[CONF_CC1101_ROLLING_SHUTTER_ID])[:-1]
    apply_diagnostic_labels(config, full.get_config_for_path(hub_path))
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


async def to_code(config):
    var = await cover.new_cover(config)
    await cg.register_component(var, config)

    parent = await cg.get_variable(config[CONF_CC1101_ROLLING_SHUTTER_ID])
    key = config[CONF_SHUTTER_ID]
    cg.add(var.set_parent(parent))
    cg.add(var.set_shutter_key(key))
    cg.add(parent.register_cover(key, var))

    await register_diagnostics(config, parent, key)
