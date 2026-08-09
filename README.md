# CC1101 Rolling Shutter

[![Tests](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml)
[![Validate](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/cdamman/home-assistant-cc1101-rolling-shutter?display_name=tag&sort=semver)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant custom integration to control rolling shutters through a CC1101
serial module (868 MHz radio).

The repository holds both halves of the setup: the Home Assistant integration
under `custom_components/`, and the [firmware](#firmware) that runs on the
Arduino-compatible board driving the CC1101, under `firmware/`.

## How it works

Every shutter is exposed as a `cover` entity. On open/close, the integration
writes the command `<id> open` or `<id> close` (e.g. `4 open`) to the serial
port at 115200 baud, then waits for the module to answer `Sending`.

Since the module never reports a real state, both the state **and a position**
(0 = closed, 100 = open) are *inferred* from the commands, cached after each
action and **restored on restart** (`RestoreEntity`).

### Behaviour in Google Home

The entity is published with the `blind` device class, so Google Home
classifies it as a **"Blind"** (not a "Shutter"). The Home Assistant icon, on
the other hand, stays a roller-shutter icon that follows the state
(open/closed).

A position is exposed (`SET_POSITION`) for two reasons: to keep the **"Stop"
button permanently available** in Google Home, and to display the open/closed
state there. Since the hardware has no intermediate position, a position
setpoint is snapped to the extremes: **< 50% → close, ≥ 50% → open**. The state
is published optimistically *before* the command is sent, which avoids the
Google tile flickering.

## Installation

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
3. In **Configure** (the integration options), add your shutters (shutter ID +
   name). You can add or remove them at any time. The ID is the index the
   firmware maps to a room — `0` to `4` with the sketch as shipped.

Deleting a shutter **device** from the UI also removes it from the options
automatically.

## Firmware

`firmware/cc1101_rolling_shutter/cc1101_rolling_shutter.ino` is the other half
of the setup: the sketch that actually talks to the radio. It runs on an
**Arduino-compatible board** (the pin names `D1`/`D4` are the ESP8266/NodeMCU
ones) wired to a **CC1101 module on 868 MHz** over SPI, and it is the device the
integration opens as a serial port.

It depends on the
[SmartRC-CC1101-Driver-Lib](https://github.com/LSatan/SmartRC-CC1101-Driver-Lib)
by Little_S@tan, installable from the Arduino Library Manager.

### Serial protocol

The sketch reads lines at 115200 baud and accepts `<id> <open|stop|close>` —
exactly what the integration writes. It echoes the line it received, then
prints `Sending codes for room <id>, cmd <n>`, which is the `Sending` the
integration waits for. That is why `serial_controller.py` reads two lines (echo,
then response).

Note that `Sending` is printed **before** the transmission starts, not after:
each command is sent as `NB_SIGNALS` (4) frames repeated `NB_RETRIES` (4) times,
so 16 frames go out after the acknowledgement, each followed by a
`2 × SIGNAL_DURATION_MS` (32 ms) gap. The radio therefore stays busy for at
least ~0.5 s once the integration has already been told `Sending`. That is what
`RF_INTERCOMMAND_DELAY` in `const.py` is sized for — see [Notes](#notes).

Anything else received on the air is dumped to the serial console as a
`{0x.., 0x.., ...}` byte array, which is how new codes get captured.

### Radio settings

Taken from the sketch: 2-FSK, 868.027 MHz minus an 83 kHz offset, 55 kHz
deviation, 9.57 kBaud, sync word `0x4b 0xd4`, 6-byte preamble, fixed packet
length, no CRC, no whitening, no Manchester, no FEC. A frame is 10 data bytes;
with the preamble, sync word and length byte that is 152 bits, about 15.9 ms on
air.

### Where the codes come from

The `codes[][][][]` table is **not** computed. The frames a rolling shutter
remote sends are specific to that remote, so they have to be captured off the
air and replayed verbatim. The originals were sniffed with an
[RTL-SDR Blog](https://www.rtl-sdr.com/) USB dongle and
[Universal Radio Hacker](https://github.com/jopohl/urh).

> **The table in this repository is placeholder data.** It is a synthetic
> pattern that will not drive any shutter — the real captures are deliberately
> not published, since these frames go out in the clear and anyone in radio
> range could replay them. You have to fill in your own.

### Capturing your own

1. Sniff your remote with an SDR (RTL-SDR Blog dongle + Universal Radio Hacker
   works well) to recover the radio parameters and the frames, and adjust the
   `ELECHOUSE_cc1101.set*` calls in `setup()` to match.
2. Once the parameters are right, the sketch itself is the easier capture tool:
   flash it and press the buttons on your remote. Every frame it hears is
   printed on the serial console as `{0x.., 0x.., ...},` — exactly the format
   the table expects, ready to paste.
3. Fill `codes[shutter][command][signal]` in the order open, stop, close, and
   rename the `SHUTTER_n` defines to suit your home.

Note that consecutive presses do not repeat the same frame, so capture a run of
them per button — `NB_SIGNALS` (4) per command in the shipped layout.

## Notes

- **RF serialization**: every command of a module goes through a shared lock —
  one transmission at a time, in order. A spacing delay
  (`RF_INTERCOMMAND_DELAY`, 0.8 s by default in `const.py`) lets each radio
  transmission finish before the next one starts, to avoid collisions when
  several shutters are operated at the same time. The default is sized for the
  bundled firmware, which acknowledges up front and then stays on air for
  ~0.5 s (see [Firmware](#firmware)). Set it to `0` if your firmware blocks
  until the transmission is done instead. Two distinct modules (two entries)
  transmit in parallel.
- Command terminator: `\n` by default (see `COMMAND_TERMINATOR` in `const.py`).
  Set it to `""` if your firmware does not expect one.
- If the serial response does not contain `Sending`, the service call fails and
  the optimistic state is rolled back.
- Make sure the Home Assistant user can access the port (`/dev/ttyUSB0`, group
  `dialout`).

## Development

The test suite runs against a real Home Assistant test harness
(`pytest-homeassistant-custom-component`), with the serial layer mocked:

```bash
pip install -r requirements_test.txt
pytest
```

Two GitHub workflows run on every push and pull request:

- `tests.yml` — the pytest suite with coverage;
- `validate.yml` — [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest)
  (manifest validation) and the [HACS action](https://github.com/hacs/action)
  (repository validation).

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

## License

[MIT](LICENSE)
