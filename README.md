# CC1101 Rolling Shutter

[![Tests](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml)
[![Validate](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml)
[![ESPHome](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/esphome.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/esphome.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/cdamman/home-assistant-cc1101-rolling-shutter?display_name=tag&sort=semver)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Control rolling shutters from Home Assistant through a CC1101 module
(868 MHz radio).

Shutters are addressed by their **4-byte radio ID**, and every frame on the air
is decoded — so shutters are **discovered automatically**, and operating one
from its original remote is **reflected in Home Assistant**.

The repository also holds the [reverse-engineered protocol](PROTOCOL.md) the
shutters speak, with a reference codec in `tools/shutter868.py`.

## Two ways to run it

| | [**ESPHome**](#esphome) | [**Integration + serial firmware**](#home-assistant-integration) |
| --- | --- | --- |
| What runs where | one ESP node, everything on it | a sketch on a board cabled to the Home Assistant host, driven by a custom integration |
| Install | `external_components:` in your YAML | HACS + a config flow, plus flashing the sketch |
| Placement | anywhere on Wi-Fi, near the shutters | within a USB cable of Home Assistant |
| Adding a shutter | edit the YAML, re-flash over the air | pick it in the integration options |

**Neither replaces the other.** They are two front-ends onto the same
[protocol](PROTOCOL.md), maintained side by side and documented in full below;
pick whichever suits where your hardware can sit and how you prefer to
configure things. A fix to the frame format or the radio parameters belongs in
both.

## How it works

The description below is written in terms of the serial setup; the ESPHome node
does exactly the same things, with the serial link collapsed into the same
microcontroller.

Every shutter is exposed as a `cover` entity, addressed by the 4-byte ID burned
into its motor — written as 8 hex digits, e.g. `12345600`. On open/close, the
integration writes `<id> open` or `<id> close` to the serial port at 115200
baud; the firmware transmits the burst and answers with a JSON `tx` event once
it is done, which is what the integration waits for.

The firmware also stays in receive mode, so **frames sent by the original
remotes are decoded and reported**. That gives two things the hardware itself
never provides:

- **State feedback** — pressing a physical remote updates the entity.
- **Discovery** — a shutter that is heard but not configured is offered in the
  integration options, so there is nothing to look up by hand.

The motors still report nothing about their position, so the state **and a
position** (0 = closed, 100 = open) remain *inferred* — now from both our own
commands and the remotes' — cached after each action and **restored on restart**
(`RestoreEntity`).

### Behaviour in Google Home

The **integration** publishes the `blind` device class, so Google Home
classifies it as a **"Blind"** (not a "Shutter"); its Home Assistant icon stays
a roller-shutter one that follows the state, which a custom integration can do
because it ships its own per-state icons.

The **ESPHome node** uses `shutter` instead, and so is a **"Shutter"** in
Google Home. ESPHome has no per-state icons of its own — they come from the
device class or not at all — so `blind` there would draw venetian blinds, and
naming an icon explicitly would freeze it open or closed. `shutter` is what
gets roller shutters that follow the state. Set `device_class: blind` on a
cover if you would rather match the integration in Google Home.

A position is exposed (`SET_POSITION`) for two reasons: to keep the **"Stop"
button permanently available** in Google Home, and to display the open/closed
state there. Since the hardware has no intermediate position, a position
setpoint is snapped to the extremes: **< 50% → close, ≥ 50% → open**. The state
is published optimistically *before* the command is sent, which avoids the
Google tile flickering.

## ESPHome

`esphome/components/cc1101_rolling_shutter/` is an [external component](https://esphome.io/components/external_components.html)
that folds both halves into a single ESPHome node: the same radio driver, the
same frame codec, the same behaviour — but talking to Home Assistant over the
native API rather than through a serial cable and a custom integration.

Nothing is copied into `custom_components/`, so there is no HACS install and no
Home Assistant restart; the node appears as a device on its own.

### Hardware

Any ESP8266 or ESP32 board wired to a **CC1101 module on 868 MHz**: hardware SPI
(`SCK`, `MISO`, `MOSI`, `CSN`) plus **GDO0** on a free GPIO. That is the same
wiring the standalone sketch expects, so an existing board can simply be
re-flashed.

On a **Wemos D1 mini**, which is what [`esphome-example.yaml`](esphome-example.yaml)
targets:

| CC1101 | D1 mini | |
| --- | --- | --- |
| `VCC` | `3V3` | never 5 V |
| `GND` | `G` | |
| `SCK` | `D5` | GPIO14 |
| `MISO` (sometimes `GDO1`) | `D6` | GPIO12 |
| `MOSI` | `D7` | GPIO13 |
| `CSN` | `D8` | GPIO15 |
| `GDO0` | `D1` | GPIO5 |
| `GDO2` | — | not used |

Only `GDO0` is configured. The four bus pins are the driver's own defaults for
the platform, so they need no YAML — and **there is no `spi:` block**: the
CC1101 driver talks to the Arduino `SPI` library directly rather than through
ESPHome's SPI component, so declaring one would set up a second, unused bus.

`cs_pin` can be moved, and on the ESP8266 it is the only one that can:

> **GPIO15 has to be low at boot** on the ESP8266, and that is the default
> `CSN`. Most CC1101 modules leave the line alone and the D1 mini's own
> pull-down wins, but one that pulls `CSN` up will stop the board from
> starting at all. `cs_pin: D2` — or any free GPIO — fixes that.

`sck_pin`, `miso_pin` and `mosi_pin` exist for the **ESP32**, where the driver
hands them to `SPI.begin()` and the GPIO matrix honours them. On the ESP8266 the
bus is the hardware peripheral on fixed pins (GPIO14/12/13); setting them to
anything else is refused during validation rather than silently ignored.

The component uses the
[SmartRC-CC1101-Driver-Lib](https://github.com/LSatan/SmartRC-CC1101-Driver-Lib)
by Little_S@tan, pulled in automatically — which ties the node to the **Arduino
framework** (`framework: type: arduino`, the ESP8266 default).

### Configuration

A complete node, also in [`esphome-example.yaml`](esphome-example.yaml):

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/cdamman/home-assistant-cc1101-rolling-shutter
    components: [cc1101_rolling_shutter]

cc1101_rolling_shutter:
  id: rf
  gdo0_pin: D1

cover:
  - platform: cc1101_rolling_shutter
    shutter_id: "12345600"
    name: Living room
```

That is a whole shutter. It is a `shutter`, and it carries all three diagnostics
— named after the cover, as *Shutter ID: Living room*, *RF code rolling
counter: Living room* and *Remote signal strength: Living room* — without any
of them being written out. Write `device_class`, `shutter_id_diagnostic`,
`rf_code_rolling_counter` or `remote_signal_strength` to override one;
`internal: true` on a diagnostic keeps it out of Home Assistant altogether.

The diagnostic is `shutter_id_diagnostic` rather than `shutter_id` because that
name is taken by the option above it — the id itself, which the shutter cannot
do without.

`shutter_id` is 8 hex digits; `:`, `-` and `.` separators are accepted, so
`12:34:56:00` and `12345600` are the same shutter. Covers and sensors take the
usual ESPHome options on top of that.

### Tuning the receive threshold

`rssi_threshold` decides what counts as noise, and the right value is a
question about your walls rather than about the protocol: too high and a remote
two rooms away goes unheard, too low and the log fills with unrecognised
frames. Finding it by editing, recompiling and re-flashing between attempts is
miserable, so it is also a `number`:

```yaml
number:
  - platform: cc1101_rolling_shutter
    name: RSSI threshold
```

Turn it in Home Assistant, press a remote, watch the log — the node applies
each change immediately. The value is kept across reboots (`restore_value:
false` to disable), and the hub's `rssi_threshold` is what it starts from the
first time. On the ESP8266 surviving a *power cut* also wants
`restore_from_flash: true`, as with shutter positions.

### Remembering where each shutter is

The motors report nothing, so the position is inferred — and therefore worth
keeping. Every change is written to the node's preferences, and restored on
boot before anything else happens; restoring only sets the entity's state, so a
reboot never puts a command on the air.

On the ESP8266 preferences live in **RTC memory** by default, which survives a
reboot and an OTA update but *not* a power cut. One line fixes that, and the
example sets it:

```yaml
esp8266:
  board: d1_mini
  restore_from_flash: true
```

Writes are batched rather than one per command, so this is not the flash-wear
hazard it sounds like. On the ESP32 preferences are in NVS and already survive
a power cut, with nothing to set.

Two things are deliberately *not* kept: the rolling counters, which resynchronise
from the first frame heard and whose receivers do not enforce monotonicity, and
the fabricated "open" a shutter starts from on a first boot — storing a guess
would make the next boot look like a genuine restore.

State is filed under the entity's name, so **renaming a shutter loses its
stored position** once; it comes back after the next command.

### One device per shutter

Home Assistant names every entity after the device it belongs to, so a node
called *Shutters* holding five covers gives you *Shutters Living room*,
*Shutters Kitchen*, and so on. There is no switching that off from the ESPHome
side — the integration always uses Home Assistant's device-plus-entity naming.

What you can do is give each shutter a **device of its own**, which is what
[`esphome-example.yaml`](esphome-example.yaml) does:

```yaml
esphome:
  name: shutters
  friendly_name: Shutters
  devices:
    - id: living_room
      name: Living room

cover:
  - platform: cc1101_rolling_shutter
    shutter_id: "12345600"
    device_id: living_room
    name: none          # an entity with no name takes its device's
    device_class: blind
    rf_code_rolling_counter:
    remote_signal_strength:
```

`name: none` is not optional shorthand for leaving the key out. Omitting `name:`
with an `id:` present makes ESPHome name the entity after that id **and mark it
`internal`**, so it never reaches Home Assistant at all; omitting both is a
validation error. `none` is what asks for "named after my device".

The cover is now simply **Living room**, and the two diagnostics follow it onto
that sub-device: they are named *Living room RF code rolling counter* and
*Living room remote signal strength*, without the node's name anywhere. The
label alone is used in this case — qualifying it would read "Living room RF
code rolling counter: Living room".

The node itself keeps its own two diagnostics, so *Shutters* remains as the
device that owns the radio.

The hub takes one required option and a set of radio parameters whose defaults
are the values these shutters were reverse-engineered against — see
[how the codes were obtained](#how-the-codes-were-obtained) before changing
them:

| Option | Default | Notes |
| --- | --- | --- |
| `gdo0_pin` | *required* | GPIO wired to the module's GDO0 |
| `cs_pin` | driver default | GPIO15 on ESP8266, GPIO5 on ESP32 |
| `sck_pin` / `miso_pin` / `mosi_pin` | driver defaults | ESP32 only; fixed by the hardware elsewhere |
| `frequency` | `867.944MHz` | 868.027 MHz with the −83 kHz offset the hardware needs |
| `deviation` | `55.0` | kHz |
| `data_rate` | `9.57` | kBaud |
| `rx_bandwidth` | `162.5` | kHz; the signal is ~120 kHz wide, and widening this only lets in noise |
| `sync_word` | `[0x4B, 0xD4]` | |
| `output_power` | `12` | dBm |
| `repeats` / `frames_per_press` | `4` / `4` | one press is 4 frames, sent 4 times |
| `burst_window` | `1500ms` | frames this close together are one press |
| `rssi_threshold` | `-95` | dBm below which a frame is treated as noise; see the `number` platform to turn it from Home Assistant |
| `discovered_shutter` | automatic | text sensor carrying the id of the last shutter heard |
| `spi_connected` | automatic | binary sensor: does the module answer on SPI |
| `diagnostic_names` | English | the labels every diagnostic is named from |

### Finding your shutter ids

Flash the node with nothing but the hub, then press a button on each original
remote: the id appears on the *Last discovered shutter* sensor and in the log.
It reports **every** shutter it hears, configured or not, so it stays useful
afterwards — pressing a remote and watching the id is how you confirm that the
`shutter_id` in your YAML is the one actually on the air.
Add it to the YAML as a `cover`, and re-flash over the air.

This is the one place the two setups genuinely differ. ESPHome entities are
created at compile time, so a discovered shutter cannot become a cover by
itself the way the integration's options flow allows — it is surfaced, and you
add it. In exchange, the configuration is a file you can read, diff and back
up.

### Diagnostics

Three per-shutter diagnostics, all created by default and all filed under the
device's **Diagnostic** section:

| Sensor | What it shows |
| --- | --- |
| `shutter_id_diagnostic` | the shutter's own 4-byte id, so it can be read off the device page instead of the YAML |
| `rf_code_rolling_counter` | the shutter's counter, 0–255, as the node last saw it — following both the frames it sends and the ones it hears |
| `remote_signal_strength` | RSSI in dBm of the last frame heard from that shutter's remotes |

Write them **on the cover**, as above: the id and the name are already there,
and a bare key is named `<label>: <cover name>` — *RF code rolling counter:
Living room*. Give one a `name:` of its own to override that entirely.

All four diagnostics — these two and the node's own pair below — are named
from labels set once on the hub. ESPHome has no translation layer, an entity
name being whatever the YAML says, so this is where a node speaks something
other than English:

```yaml
cc1101_rolling_shutter:
  gdo0_pin: D1
  diagnostic_names:
    rf_code_rolling_counter: Compteur cyclique du code RF
    remote_signal_strength: Puissance du signal de la télécommande
    shutter_id_diagnostic: Identifiant RF
    discovered_shutter: Dernier volet découvert
    spi_connected: Liaison SPI
```

giving *Compteur cyclique du code RF: Living room*. Any label can be set on its
own; the rest keep their English defaults. The node's two take the label as
their whole name, having only the one node to belong to, while the per-shutter
pair is qualified by the shutter.

The two numeric ones are also a `sensor:` platform of their own, which repeats
the id and takes no label — a name written there is used exactly as given:

```yaml
sensor:
  - platform: cc1101_rolling_shutter
    shutter_id: aa:bb:ccdd
    remote_signal_strength:
      name: Neighbour remote signal strength
```

That form is what remains for a shutter with **no cover** — one you only
listen to, such as a neighbour's, or your own before you are ready to command
it.

If even one block per shutter is too much repetition, ESPHome's
[packages](https://esphome.io/guides/configuration-types.html#packages) take
variables, which is as close to a loop as the YAML gets:

```yaml
packages:
  living_room: !include {file: shutter.yaml, vars: {id: "12345600", name: Living room}}
  kitchen:     !include {file: shutter.yaml, vars: {id: 0a:1b:2c:01, name: Kitchen}}
```

with `shutter.yaml` holding one `cover:` entry written in terms of
`${id}` and `${name}`.

The node carries two of its own, and those need no declaring at all — they
appear from a `cc1101_rolling_shutter:` with nothing in it but a `gdo0_pin`:

| Sensor | What it shows |
| --- | --- |
| `spi_connected` | **is the radio there at all** |
| `discovered_shutter` | the id of the last shutter heard on the air, configured or not |

Write either key to give it options — `disabled_by_default: true` to keep it
out of the way, `internal: true` to keep it off Home Assistant entirely.

`spi_connected` reads the module's version register: on at boot if the CC1101
answers, and re-checked every minute afterwards, so a connector working loose
shows up rather than presenting as shutters that quietly stopped responding. Without a
radio the node still boots and still exposes its covers — it simply never hears
or sends anything, which is a miserable thing to diagnose from the outside.
This is the entity that tells you the wiring is right *before* you have any
shutters to try.

A missing module is treated as recoverable rather than fatal: the component
carries an error status instead of marking itself failed, retries every five
seconds, and configures the radio from scratch when one appears — so plugging
it in is enough, with no reboot. Commands issued while it is absent are refused
with a warning rather than transmitted into nothing.

The counter carries the unit `/ 256`, which is not decoration. Home Assistant
treats a sensor with neither a unit nor a state class as non-numeric: it prints
the state verbatim — `47.0`, since the ESPHome API carries floats — and offers
no *Display precision* control to round it with. Either a unit or a state class
makes it numeric and lets `accuracy_decimals: 0` through, but only the state
class would also record **long-term statistics** — that is the sole thing
`sensor/recorder.py` filters on — and hourly means of a counter that wraps at
255 earn nobody anything. Hence the unit — and `/ 256` rather than something
invented, since *47 / 256* says what the number actually is: a position in a
cycle, not a quantity of anything.

Override either on the sensor: `unit_of_measurement: ""` to drop it (and get
the decimal back), or `state_class: measurement` if you do want the history.

The integration publishes a `source` attribute on the first and a
`last_command` attribute on the second. ESPHome entities carry no custom
attributes, so those are not reproduced; the log line for every frame carries
the same information.

A frame that is structurally ours but fails validation — noise, or the fourth
button nobody has captured yet — is logged as a warning with the payload
unmasked, which is what the serial firmware's `raw` event does.

### Moving between the two

Shutter ids are the same on both sides, so nothing has to be re-discovered:
read each one off its device page in Home Assistant and paste it into the YAML,
or the other way round.

They can also run **at the same time**, which is what makes switching painless —
one radio per room, say, or one setup left in place until the other has proved
itself. The only rule is that a given shutter should have **one
transmitter**: two receivers on the same frequency do not interfere, and both
resynchronise their counters from whatever they hear, but two things sending on
the same press is asking for trouble.

Entity ids differ between the two (each names its own entities), so anything
referencing them — automations, dashboards, voice assistant exposure — needs
pointing at whichever set you keep.

## Home Assistant integration

A custom integration in `custom_components/`, talking over a serial port to the
[sketch](#firmware) in `firmware/` on a cabled Arduino-compatible board. It
came first, and it is the one to pick when the radio can live next to the Home
Assistant host and you would rather add shutters by clicking than by editing a
file.

### Through HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cdamman&repository=home-assistant-cc1101-rolling-shutter&category=integration)

1. Click the button above (or add
   `https://github.com/cdamman/home-assistant-cc1101-rolling-shutter` as a
   **custom repository** of category **Integration** in HACS).
2. Download the integration, then restart Home Assistant.

### Manually

1. Copy the `custom_components/cc1101_rolling_shutter/` folder into your Home
   Assistant configuration (`<config>/custom_components/`).
2. Restart Home Assistant.

### Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cc1101_rolling_shutter)

1. **Settings → Devices & services → Add integration →
   "CC1101 Rolling Shutter"** (or click the button above).
2. Fill in the port (`/dev/ttyUSB0`) and the baud rate (`115200`).
3. Press a button on each original remote. The firmware hears the frame and
   the shutter appears as **discovered**.
4. In **Configure** (the integration options), pick a discovered shutter and
   give it a name — or type its 4-byte ID by hand (`12345600` or
   `12:34:56:00`). You can add or remove shutters at any time.

Deleting a shutter **device** from the UI also removes it from the options
automatically.

### Diagnostics

Each shutter carries two diagnostic sensors. They are filed under the device's
**Diagnostic** section rather than mixed in with the shutter's controls.

| Sensor | What it shows |
| --- | --- |
| **RF code rolling counter** | the shutter's counter, 0–255, as the firmware last saw it. A `source` attribute says whether the value came from a frame we sent (`sent`) or one heard on the air (`air`). |
| **Remote signal strength** | RSSI in dBm of the last frame heard from that shutter's remotes, with a `last_command` attribute saying which command that frame carried. |

Both are unknown until the radio says something about the shutter, and neither
is restored across restarts: the firmware does not persist its counter table
either, so a value carried over would be a lie.

Only frames heard on the air carry a signal level, so sending a command never
touches the signal strength: our own `tx` events report none.

## Firmware

`firmware/cc1101_rolling_shutter/cc1101_rolling_shutter.ino` is the other half
of the setup: the sketch that talks to the radio. It runs on an
**Arduino-compatible board** (the pin names `D1`/`D4` are the ESP8266/NodeMCU
ones) wired to a **CC1101 module on 868 MHz** over SPI, and it is the device the
integration opens as a serial port.

It depends on the
[SmartRC-CC1101-Driver-Lib](https://github.com/LSatan/SmartRC-CC1101-Driver-Lib)
by Little_S@tan, installable from the Arduino Library Manager.

The sketch is a **pure protocol bridge**: it holds no device list and no
captured codes. Frames are built from the 4-byte ID it is given, so there is
nothing installation-specific to publish — it is anonymous by design, and the
same binary works in any home.

### Serial protocol

One command per line at 115200 baud:

| Line | Effect |
| --- | --- |
| `<id> open` \| `up` | raise the shutter |
| `<id> stop` | stop it |
| `<id> close` \| `down` | lower it |
| `status` | dump the rolling-counter table |

`<id>` is 8 hex digits; `:`, `-` and `.` separators are accepted, so
`12:34:56:00` and `12345600` are the same shutter.

Everything the sketch does is reported as one JSON object per line:

```json
{"event":"ready"}
{"event":"tx","id":"12345600","cmd":"close","counter":47}
{"event":"rx","id":"12345600","cmd":"open","counter":51,"rssi":-62}
{"event":"error","reason":"bad id","input":"nope"}
{"event":"raw","rssi":-79,"data":"...","unmasked":"..."}
```

Two of those matter to the integration:

- **`tx`** is printed *after* the whole burst has gone out — 4 frames repeated
  4 times, roughly half a second. Waiting for it both surfaces failures and
  guarantees two commands never overlap on the air, which is why the
  integration no longer needs a fixed inter-command delay.
- **`rx`** is a frame from one of the original remotes. It is what drives state
  feedback and discovery.

An `raw` line is a frame that failed validation — noise, or the fourth button
nobody has captured yet. When the checksum is right it also prints the payload
unmasked, which is exactly what is needed to identify an unknown command.

### Protocol and tooling

[`PROTOCOL.md`](PROTOCOL.md) documents the radio parameters and the frame
format: a 10-byte payload whose rolling counter doubles as the XOR mask over
the ID and command fields, plus two integrity bytes and a sum checksum. It is
obfuscation rather than encryption — there is no secret key — and the document
is explicit about what is still unknown.

`tools/shutter868.py` is a dependency-free Python implementation of that codec:
`encode`, `decode`, a burst de-duplicator and the published test vectors. The
integration does not use it — the firmware does the encoding — but it is the
executable reference for anyone writing another bridge, and the test suite
checks it against the documented vectors.

> **Security.** The protocol has no authentication: a plaintext counter, a
> reversible mask and a sum checksum. Anyone in radio range can recover a
> shutter ID and forge valid frames, and receivers accept replayed frames. That
> is unremarkable for this class of hardware, but worth knowing before exposing
> anything on the basis of it.

### How the codes were obtained

None of this was documented anywhere: the protocol was recovered by listening
to the original remotes with an [RTL-SDR Blog](https://www.rtl-sdr.com/) USB
dongle and [Universal Radio Hacker](https://github.com/jopohl/urh), then
decoding 60 captured frames (5 shutters × 3 buttons × 4 frames) until every
rule held on all of them and re-encoding reproduced the original bytes.

**The result of that work is written up in [`PROTOCOL.md`](PROTOCOL.md)**: the
physical layer, the frame layout and its XOR mask, the command encoding, how
the rolling counter behaves — and, just as usefully, the questions that are
still open.

The CC1101 is deaf until it is tuned exactly right, so the SDR is not
optional — it is how you find the settings the radio needs. If your shutters
are not the ones described here, redo this pass with your own remote:

1. **Find the frequency.** Watch the spectrum around the ISM band (868 MHz in
   Europe, 433 MHz elsewhere) while holding a button. The burst is short, so
   use a waterfall and press repeatedly. Here it landed on **868.027 MHz**.
2. **Identify the modulation.** Two close carriers alternating is 2-FSK; a
   carrier switching on and off is OOK/ASK. Measure the spacing between the two
   tones — half of it is the **deviation** (55 kHz here).
3. **Measure the symbol rate.** Zoom in on the demodulated signal in URH and
   read the shortest symbol; its inverse is the **data rate** (9.57 kBaud).
4. **Read the preamble and sync word.** The leading `10101010…` is the
   preamble; the bytes right after it, identical in every frame, are the sync
   word (`0x4B 0xD4`, after 6 preamble bytes).
5. **Transfer it to the sketch.** Each measurement maps to one call in
   `setup()`:

   | Measurement | Call |
   | --- | --- |
   | frequency | `setMHZ(868.027 - 0.083)` |
   | modulation | `setModulation(0)` — 0 = 2-FSK |
   | deviation | `setDeviation(55.00)` |
   | data rate | `setDRate(9.57)` |
   | preamble length | `setPRE(3)` — 3 = 6 bytes |
   | sync word | `setSyncWord(0x4b, 0xd4)` |
   | payload length | `setPacketLength(SIGNAL_LEN_BYTES + 1)` |

   The `- 0.083` is a deliberate **−83 kHz offset**: the CC1101's synthesiser
   and the remote's cheap oscillator do not land on exactly the same nominal
   frequency, and this compensates. Expect to trim it for your own hardware —
   if frames are received intermittently or not at all while the frequency
   looks right, sweep this offset a few tens of kHz either way.

6. **Let the sketch finish the job.** Once the radio parameters match, you no
   longer need the SDR: flash the firmware and press the remote. Valid frames
   come out as `rx` lines carrying the shutter ID directly, and anything that
   fails validation comes out as a `raw` line with the payload unmasked —
   which is how an unknown button, such as the pairing one described in
   [`PROTOCOL.md`](PROTOCOL.md), would be identified.

## Notes

- **One transmission at a time**: every command for a module goes through a
  shared lock and waits for the firmware's `tx` acknowledgement, which arrives
  once the burst is fully transmitted. That is what keeps two shutters from
  colliding on the air; no timing constant to tune. Two distinct modules (two
  entries) still transmit in parallel.
- If the firmware does not acknowledge within `SERIAL_TIMEOUT` (5 s in
  `const.py`), or answers with an `error` event, the service call fails and the
  optimistic state is rolled back.
- The reader reconnects on its own: if the port disappears it is reopened every
  `RECONNECT_DELAY` seconds, so unplugging the module does not require a
  reload.
- **Rolling counters live in the firmware**, one per shutter ID, resynchronised
  from every frame heard on the air. They are deliberately not persisted:
  receivers do not enforce monotonicity, so a reboot is harmless.
- Make sure the Home Assistant user can access the port (`/dev/ttyUSB0`, group
  `dialout`).

### Upgrading from a pre-protocol install

Shutters used to be addressed by the index hardcoded in the old sketch (`0` to
`4`). Those values mean nothing to the new firmware, and cannot be translated —
the 4-byte ID has to be read off the air. On upgrade the integration migrates
the config entry, drops those shutters and logs which ones were removed. Flash
the new sketch, press a button on each remote and re-add them from the options,
where they appear as discovered.

## Development

The test suite runs against a real Home Assistant test harness
(`pytest-homeassistant-custom-component`), with the serial layer replaced by a
fake firmware that replays JSON events. It also checks `tools/shutter868.py`
against the vectors published in [`PROTOCOL.md`](PROTOCOL.md):

```bash
pip install -r requirements_test.txt
pytest
```

The ESPHome component is checked separately, since none of it is Python that
pytest can import:

```bash
# the frame codec, against the vectors published in PROTOCOL.md
c++ -std=c++17 -Wall -Wextra -Werror -o test_protocol tests/firmware/test_protocol.cpp
./test_protocol

# the schemas, the validators and the code generation
pip install esphome
esphome config tests/esphome/local.yaml
```

`esphome/components/cc1101_rolling_shutter/protocol.h` is deliberately free of Arduino and
ESPHome so that first command needs nothing but a compiler. It is the piece
where a mistake is silent — a wrong byte builds fine and simply fails to move a
shutter — and it is now pinned by three independent implementations of one
specification: the sketch, `tools/shutter868.py` and the component.

Four GitHub workflows run on pushes and pull requests:

- `tests.yml` — the pytest suite with coverage;
- `validate.yml` — [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest)
  (manifest validation) and the [HACS action](https://github.com/hacs/action)
  (repository validation);
- `firmware.yml` — compiles the sketch for `esp8266:esp8266:nodemcuv2` with
  `arduino-cli`, on every change under `firmware/`. The Python suite cannot
  catch a broken sketch, and the failure worth catching is a preprocessing one:
  the Arduino builder hoists generated prototypes above the first function
  definition, which is why the sketch forward-declares `struct Device`.
  `tests/test_firmware_compiles.py` runs the same compile locally when
  `arduino-cli` is installed, and skips otherwise;
- `esphome.yml` — the two commands above, plus an `esphome compile` for
  `nodemcuv2` of both `tests/esphome/local.yaml` and `tests/esphome/minimal.yaml`
  (the bare hub you flash first, with no cover and no sensor declared). That
  last job is the only one that cross-compiles the component's C++ for the
  board it runs on, so it is the slow one and the one that catches what the
  others cannot.

### Cutting a release

Publish a GitHub release on a tag such as `v1.2.0` — that is the whole
procedure. `release.yml` then stamps the version into `manifest.json`, zips the
integration and attaches `cc1101_rolling_shutter.zip` to the release, which is
what HACS downloads (`zip_release` in `hacs.json`).

The version therefore lives in the tag, not in the repository: the committed
`manifest.json` deliberately keeps a placeholder `0.0.0`, and only the copy
inside the release asset carries the real number. Two consequences worth
knowing:

- Nothing has to be committed to bump a version, and the tag can never drift
  from what Home Assistant reports.
- Downloading the **default branch** from HACS bypasses the asset, so such an
  install reports `0.0.0`. Install a release for a meaningful version.

The zip is built from inside `custom_components/cc1101_rolling_shutter/`, so
`manifest.json` sits at its root — HACS extracts the archive directly into
`<config>/custom_components/cc1101_rolling_shutter`.

None of this touches the ESPHome component: `external_components` clones the
repository, so a node follows whatever branch or tag its `source:` names, and
releases only ever concern the custom integration. Pin one with
`ref: v1.2.0` under `source:` if you would rather not track `main`.

## License

[MIT](LICENSE)
