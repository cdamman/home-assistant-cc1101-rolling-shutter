"""CC1101 868 MHz roller shutter bridge.

One `cc1101_rolling_shutter` hub drives a single CC1101 module: it transmits commands
and decodes every frame it hears, including the ones the original remotes send.
See PROTOCOL.md for the radio parameters and the frame format.
"""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import pins
from esphome.components import binary_sensor, text_sensor
# Aliased: this package has a sensor.py of its own, and importing it
# rebinds the name here — the submodule becomes an attribute of the very
# namespace this line writes into.
from esphome.components import sensor as sensor_component
from esphome.const import (
    CONF_ID,
    CONF_DEVICE_ID,
    CONF_INTERNAL,
    CONF_FREQUENCY,
    CONF_NAME,
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_SIGNAL_STRENGTH,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    UNIT_DECIBEL_MILLIWATT,
)
from esphome.core import CORE

CODEOWNERS = ["@cdamman"]
MULTI_CONF = True
# The hub's sources reference both unconditionally — shutter_cover.cpp is
# compiled whether or not any cover is declared, and using discovered_shutter
# defines USE_TEXT_SENSOR. Without this, ESPHome defines the macro but never
# copies the base component into the build tree, and the node fails to compile.
AUTO_LOAD = ["binary_sensor", "cover", "sensor", "text_sensor"]

cc1101_rolling_shutter_ns = cg.esphome_ns.namespace("cc1101_rolling_shutter")
CC1101RollingShutter = cc1101_rolling_shutter_ns.class_("CC1101RollingShutter", cg.Component)

CONF_CC1101_ROLLING_SHUTTER_ID = "cc1101_rolling_shutter_id"
CONF_SHUTTER_ID = "shutter_id"
CONF_GDO0_PIN = "gdo0_pin"
CONF_SCK_PIN = "sck_pin"
CONF_MISO_PIN = "miso_pin"
CONF_MOSI_PIN = "mosi_pin"
CONF_CS_PIN = "cs_pin"
CONF_DEVIATION = "deviation"
CONF_DATA_RATE = "data_rate"
CONF_RX_BANDWIDTH = "rx_bandwidth"
CONF_SYNC_WORD = "sync_word"
CONF_OUTPUT_POWER = "output_power"
CONF_REPEATS = "repeats"
CONF_FRAMES_PER_PRESS = "frames_per_press"
CONF_BURST_WINDOW = "burst_window"
CONF_RSSI_THRESHOLD = "rssi_threshold"
CONF_DISCOVERED_SHUTTER = "discovered_shutter"
CONF_SPI_CONNECTED = "spi_connected"
CONF_ROLLING_COUNTER = "rf_code_rolling_counter"
CONF_SIGNAL_STRENGTH = "remote_signal_strength"
CONF_SHUTTER_ID_DIAGNOSTIC = "shutter_id_diagnostic"
CONF_DIAGNOSTIC_NAMES = "diagnostic_names"

BUS_PINS = [CONF_SCK_PIN, CONF_MISO_PIN, CONF_MOSI_PIN]
SPI_PINS = BUS_PINS + [CONF_CS_PIN]

# What the driver would pick for itself, from SmartRC_CC1101.cpp. Worth knowing
# how it uses them: on ESP32 it passes all four to SPI.begin(), and the GPIO
# matrix puts the bus wherever it is told. Everywhere else it calls the plain
# Arduino SPI.begin(), which is the hardware peripheral on fixed pins — the
# values are then only used for pinMode() and idle levels, so moving one would
# leave the bus where it was and drive an unrelated GPIO. Only CS really moves.
DRIVER_SPI_DEFAULTS = {
    "esp8266": {CONF_SCK_PIN: 14, CONF_MISO_PIN: 12, CONF_MOSI_PIN: 13, CONF_CS_PIN: 15},
    "esp32": {CONF_SCK_PIN: 18, CONF_MISO_PIN: 19, CONF_MOSI_PIN: 23, CONF_CS_PIN: 5},
}


# The two per-shutter diagnostics.
DIAGNOSTIC_SCHEMAS = {
    CONF_ROLLING_COUNTER: sensor_component.sensor_schema(
        icon="mdi:counter",
        accuracy_decimals=0,
        # Home Assistant treats a sensor with neither a unit nor a state class
        # as non-numeric: it prints the state verbatim — "47.0", the float the
        # API carries — and offers no display-precision control to round it
        # with. Either of the two makes it numeric, so accuracy_decimals above
        # takes effect; a unit is the one that does it without side effects.
        #
        # A state class would also record long-term statistics, which is what
        # sensor/recorder.py filters on and nothing else — hourly means of a
        # counter that wraps at 255 are not worth a row each. So: a unit, and
        # "/ 256" because it reads as what the number is, a position in a cycle
        # rather than a quantity of anything. Add `state_class: measurement` on
        # the sensor if you do want the history.
        unit_of_measurement="/ 256",
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
    CONF_SIGNAL_STRENGTH: sensor_component.sensor_schema(
        # Overrides the antenna the signal_strength device class would give it:
        # this is the strength of a *remote*, not of the node's own uplink.
        icon="mdi:remote",
        unit_of_measurement=UNIT_DECIBEL_MILLIWATT,
        accuracy_decimals=0,
        device_class=DEVICE_CLASS_SIGNAL_STRENGTH,
        state_class=STATE_CLASS_MEASUREMENT,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
    CONF_SHUTTER_ID_DIAGNOSTIC: text_sensor.text_sensor_schema(
        icon="mdi:identifier",
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
}

# Which of them the `sensor:` platform can carry: the id is a text sensor and
# has no business there, and it would be a poor fit anyway — that platform is
# for a shutter with no cover, and this diagnostic only repeats what such a
# config already writes down.
SENSOR_DIAGNOSTICS = [CONF_ROLLING_COUNTER, CONF_SIGNAL_STRENGTH]

# What creates each one, and what it is handed to on the hub.
DIAGNOSTIC_KINDS = {
    CONF_ROLLING_COUNTER: (sensor_component.new_sensor, "set_counter_sensor"),
    CONF_SIGNAL_STRENGTH: (sensor_component.new_sensor, "set_rssi_sensor"),
    CONF_SHUTTER_ID_DIAGNOSTIC: (text_sensor.new_text_sensor, "set_id_sensor"),
}

# As written on the `sensor` platform: ordinary sensors, named by hand.
DIAGNOSTIC_SCHEMA = {
    cv.Optional(key): DIAGNOSTIC_SCHEMAS[key] for key in SENSOR_DIAGNOSTICS
}

# As written on a cover, where validation waits until there is a name to
# inherit — a sensor schema rejects an entity with neither id nor name, which
# is exactly what `rf_code_rolling_counter:` on its own looks like at this
# point. YAML hands a bare key over as None, hence the Any.
DEFERRED_DIAGNOSTIC_SCHEMA = {
    cv.Optional(key, default={}): cv.Any(None, cv.Schema(dict))
    for key in DIAGNOSTIC_SCHEMAS
}

# The node's own two diagnostics, which belong to no shutter in particular.
NODE_DIAGNOSTIC_SCHEMAS = {
    CONF_DISCOVERED_SHUTTER: text_sensor.text_sensor_schema(
        icon="mdi:radar",
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
    CONF_SPI_CONNECTED: binary_sensor.binary_sensor_schema(
        device_class=DEVICE_CLASS_CONNECTIVITY,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
}

# Both are created whether or not the YAML mentions them: they are the node's
# own health, they cost two entities, and needing to have declared one is a
# poor thing to discover while wondering why nothing works. Write the key to
# add options — `internal: true` to keep one off Home Assistant entirely.
DEFERRED_NODE_DIAGNOSTIC_SCHEMA = {
    cv.Optional(key, default={}): cv.Any(None, cv.Schema(dict))
    for key in NODE_DIAGNOSTIC_SCHEMAS
}

# What each diagnostic is called. English by default and overridable on the
# hub, because these strings reach Home Assistant as entity names and ESPHome
# has no translation layer to put them through.
#
# The per-shutter pair is qualified by the shutter it belongs to; the node's
# two are not, having only the one node to belong to.
SHUTTER_DIAGNOSTIC_LABELS = {
    CONF_ROLLING_COUNTER: "RF code rolling counter",
    CONF_SIGNAL_STRENGTH: "Remote signal strength",
    CONF_SHUTTER_ID_DIAGNOSTIC: "Shutter ID",
}
NODE_DIAGNOSTIC_LABELS = {
    CONF_DISCOVERED_SHUTTER: "Last discovered shutter",
    CONF_SPI_CONNECTED: "CC1101: SPI Link",
}
DIAGNOSTIC_LABELS = {**SHUTTER_DIAGNOSTIC_LABELS, **NODE_DIAGNOSTIC_LABELS}

DIAGNOSTIC_NAMES_SCHEMA = cv.Schema(
    {
        cv.Optional(key, default=label): cv.string_strict
        for key, label in DIAGNOSTIC_LABELS.items()
    }
)

# Marks, on a cover's config, which diagnostics were named after it. Only those
# are relabelled later; a name written by hand is left alone.
KEY_INHERITED_NAMES = "inherited_diagnostic_names"


def diagnostic_name(label, shutter_name):
    """The one place the two halves are joined."""
    return f"{label}: {shutter_name}"


def inherited_diagnostic_name(label, shutter_name):
    """What an unnamed diagnostic is called, given its cover's name.

    A cover on a sub-device of its own has no name — Home Assistant names such
    an entity after the device — and there the label stands alone, because Home
    Assistant will put the shutter's name in front of it anyway. Qualifying it
    here as well would read "Living room RF code rolling counter: Living room".
    """
    return diagnostic_name(label, shutter_name) if shutter_name else label


def shutter_display_name(config):
    """The cover's name, or None when it has none a person would recognise.

    A cover written with an `id:` and no `name:` is named after that id by
    ESPHome and marked internal — a firmware-only entity, invisible to Home
    Assistant. Borrowing that name would label a *visible* diagnostic
    "RF code rolling counter: living_room_cover".
    """
    name = config.get(CONF_NAME)
    entity_id = config.get(CONF_ID)
    if config.get(CONF_INTERNAL) and entity_id is not None and name == entity_id.id:
        return None
    return name


def validate_inherited_diagnostics(config):
    """Name the diagnostics after their cover, then validate them properly.

    The label is the English default at this point: the hub carries the real
    one, and its config is out of reach until final validation, which is where
    apply_diagnostic_labels() finishes the job.
    """
    shutter_name = shutter_display_name(config)
    device_id = config.get(CONF_DEVICE_ID)
    inherited = []
    for key, schema in DIAGNOSTIC_SCHEMAS.items():
        if key not in config:
            continue
        entry = dict(config[key] or {})
        # Follow the cover onto its sub-device: a diagnostic left on the node
        # would be one of several identically named ones, with nothing to say
        # which shutter it belongs to.
        if device_id is not None:
            entry.setdefault(CONF_DEVICE_ID, device_id)
        if not entry.get(CONF_NAME) and CONF_ID not in entry:
            if not shutter_name and device_id is None:
                # Both diagnostics are on by default, so a cover with no name
                # to lend and no device to borrow one from must not be a hard
                # error — it would refuse configurations that were fine before
                # the default. Drop the ones nobody asked for by name, and
                # complain only about a diagnostic that was written out.
                if not entry:
                    del config[key]
                    continue
                raise cv.Invalid(
                    f"{key} has no name, and the cover has neither a name to "
                    "lend it nor a device_id to take one from — give the "
                    "cover a name, or put it on a device with `name: none`",
                    [key],
                )
            entry[CONF_NAME] = inherited_diagnostic_name(
                DIAGNOSTIC_LABELS[key], shutter_name
            )
            inherited.append(key)
        with cv.prepend_path([key]):
            config[key] = schema(entry)
    if inherited:
        config[KEY_INHERITED_NAMES] = inherited
    return config


def validate_node_diagnostics(config):
    """Name the node's own diagnostics from the labels beside them.

    No final validation needed here, unlike the per-shutter pair: the labels
    live in this very config.
    """
    labels = config[CONF_DIAGNOSTIC_NAMES]
    for key, schema in NODE_DIAGNOSTIC_SCHEMAS.items():
        if key not in config:
            continue
        entry = dict(config[key] or {})
        if not entry.get(CONF_NAME) and CONF_ID not in entry:
            entry[CONF_NAME] = labels[key]
        with cv.prepend_path([key]):
            config[key] = schema(entry)
    return config


def apply_diagnostic_labels(config, hub_config):
    """Re-label the inherited names now that the hub's labels are readable.

    Renaming in place is safe here: ids were allocated during validation and
    are untouched, and the entity's object id is derived from the name later,
    at code generation.
    """
    labels = hub_config[CONF_DIAGNOSTIC_NAMES]
    shutter_name = shutter_display_name(config)
    for key in config.get(KEY_INHERITED_NAMES, []):
        config[key][CONF_NAME] = inherited_diagnostic_name(labels[key], shutter_name)


async def register_diagnostics(config, parent, key):
    """Create whichever diagnostics `config` asks for and wire them to `key`."""
    for conf_key, (new_entity, setter) in DIAGNOSTIC_KINDS.items():
        if conf_key in config:
            entity = await new_entity(config[conf_key])
            cg.add(getattr(parent, setter)(key, entity))


def shutter_key(value):
    """A 4-byte shutter identifier, written as 8 hex digits.

    Accepts the separators the documentation uses, so 12:34:56:00 and 12345600
    are the same shutter. Returns the packed 32-bit key the component indexes
    shutters by.
    """
    value = cv.string_strict(value)
    cleaned = value.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(cleaned) != 8:
        raise cv.Invalid(
            f"a shutter id is 4 bytes, written as 8 hex digits, got {value!r}"
        )
    try:
        return int(cleaned, 16)
    except ValueError as err:
        raise cv.Invalid(f"{value!r} is not hexadecimal") from err


def _validate_spi_pins(config):
    """Resolve the bus, refusing to pretend a fixed pin can be moved."""
    if not any(key in config for key in SPI_PINS):
        return config

    defaults = DRIVER_SPI_DEFAULTS.get(CORE.target_platform)
    if defaults is None:
        missing = [key for key in SPI_PINS if key not in config]
        if missing:
            raise cv.Invalid(
                "this platform has no known default bus, so give all of "
                + ", ".join(SPI_PINS),
                [missing[0]],
            )
        return config

    if not CORE.is_esp32:
        for key in BUS_PINS:
            if key in config and config[key] != defaults[key]:
                raise cv.Invalid(
                    f"SPI is driven by the hardware peripheral here, so {key} is "
                    f"fixed at GPIO{defaults[key]}; cs_pin is the one that moves",
                    [key],
                )

    # The driver takes all four together, so fill in whatever was left out.
    for key in SPI_PINS:
        config.setdefault(key, defaults[key])
    return config


def sync_word(value):
    """Two bytes, as [high, low]."""
    value = cv.ensure_list(cv.hex_uint8_t)(value)
    if len(value) != 2:
        raise cv.Invalid("sync_word takes exactly two bytes")
    return value


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(CC1101RollingShutter),
        cv.Required(CONF_GDO0_PIN): pins.internal_gpio_input_pin_number,
        # The bus itself is optional: left out, the driver uses its own
        # defaults for the platform. cs_pin is the one worth moving on the
        # ESP8266, where the default is GPIO15 and that pin has to be low for
        # the board to boot at all.
        cv.Optional(CONF_SCK_PIN): pins.internal_gpio_output_pin_number,
        cv.Optional(CONF_MISO_PIN): pins.internal_gpio_input_pin_number,
        cv.Optional(CONF_MOSI_PIN): pins.internal_gpio_output_pin_number,
        cv.Optional(CONF_CS_PIN): pins.internal_gpio_output_pin_number,
        # 868.027 MHz with the -83 kHz offset the hardware needs; see the
        # README on re-deriving these for a different installation.
        cv.Optional(CONF_FREQUENCY, default="867.944MHz"): cv.All(
            cv.frequency, cv.float_range(min=300e6, max=928e6)
        ),
        cv.Optional(CONF_DEVIATION, default=55.0): cv.float_range(min=1.58, max=380.85),
        cv.Optional(CONF_DATA_RATE, default=9.57): cv.float_range(min=0.02, max=1621.83),
        # 162.5 kHz, not the 812.5 the chip will accept: the signal is 2 x 55
        # kHz of deviation plus 9.57 kBaud, so about 120 kHz wide, and the next
        # filter the CC1101 offers above that is 162.5. Opening it further only
        # lets in noise — wide enough and the sync detector stops firing at
        # all, which looks exactly like a disconnected antenna.
        cv.Optional(CONF_RX_BANDWIDTH, default=162.5): cv.float_range(
            min=58.03, max=812.5
        ),
        cv.Optional(CONF_SYNC_WORD, default=[0x4B, 0xD4]): sync_word,
        cv.Optional(CONF_OUTPUT_POWER, default=12): cv.int_range(min=-30, max=12),
        cv.Optional(CONF_REPEATS, default=4): cv.int_range(min=1, max=16),
        cv.Optional(CONF_FRAMES_PER_PRESS, default=4): cv.int_range(min=1, max=16),
        cv.Optional(CONF_BURST_WINDOW, default="1500ms"): cv.positive_time_period_milliseconds,
        # Frames fainter than this are noise that tripped the sync detector.
        cv.Optional(CONF_RSSI_THRESHOLD, default=-95): cv.int_range(min=-128, max=0),
        # The labels every diagnostic is named from, so a node can speak
        # something other than English.
        cv.Optional(CONF_DIAGNOSTIC_NAMES, default={}): DIAGNOSTIC_NAMES_SCHEMA,
        # discovered_shutter publishes the id of the last shutter heard on the
        # air, configured or not — entities cannot be created at runtime, so
        # this is what turns a press on an unknown remote into something you
        # can paste into the YAML, and what confirms the id of a known one.
        # spi_connected says whether the module answers at all:
        # without a radio the node still boots, still exposes its covers, and
        # simply never hears or sends anything.
        #
        # Both are validated by validate_node_diagnostics(), once the labels
        # above have supplied whatever name was not written by hand.
        **DEFERRED_NODE_DIAGNOSTIC_SCHEMA,
    }
).extend(cv.COMPONENT_SCHEMA).add_extra(_validate_spi_pins).add_extra(
    validate_node_diagnostics
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    cg.add(var.set_gdo0_pin(config[CONF_GDO0_PIN]))
    if CONF_CS_PIN in config:
        cg.add(
            var.set_spi_pins(
                config[CONF_SCK_PIN],
                config[CONF_MISO_PIN],
                config[CONF_MOSI_PIN],
                config[CONF_CS_PIN],
            )
        )
    cg.add(var.set_frequency(config[CONF_FREQUENCY] / 1e6))
    cg.add(var.set_deviation(config[CONF_DEVIATION]))
    cg.add(var.set_data_rate(config[CONF_DATA_RATE]))
    cg.add(var.set_rx_bandwidth(config[CONF_RX_BANDWIDTH]))
    cg.add(var.set_sync_word(config[CONF_SYNC_WORD][0], config[CONF_SYNC_WORD][1]))
    cg.add(var.set_output_power(config[CONF_OUTPUT_POWER]))
    cg.add(var.set_repeats(config[CONF_REPEATS]))
    cg.add(var.set_frames_per_press(config[CONF_FRAMES_PER_PRESS]))
    cg.add(var.set_burst_window(config[CONF_BURST_WINDOW]))
    cg.add(var.set_rssi_threshold(config[CONF_RSSI_THRESHOLD]))

    if CONF_DISCOVERED_SHUTTER in config:
        sensor = await text_sensor.new_text_sensor(config[CONF_DISCOVERED_SHUTTER])
        cg.add(var.set_discovered_sensor(sensor))

    if CONF_SPI_CONNECTED in config:
        connected = await binary_sensor.new_binary_sensor(config[CONF_SPI_CONNECTED])
        cg.add(var.set_spi_sensor(connected))

    # The radio configuration in setup() is known-good against these shutters,
    # so the driver that produced it is reused rather than reimplemented. It
    # ties the component to the Arduino framework.
    #
    # The driver includes <SPI.h> without declaring it, and PlatformIO only
    # links an Arduino library that something asks for — hence the second call.
    cg.add_library("SPI", None)
    cg.add_library(
        "SmartRC-CC1101-Driver-Lib",
        None,
        "https://github.com/LSatan/SmartRC-CC1101-Driver-Lib",
    )
