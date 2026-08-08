# CC1101 Rolling Shutter

[![Tests](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml)
[![Validate](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/cdamman/home-assistant-cc1101-rolling-shutter?display_name=tag&sort=semver)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant custom integration to control rolling shutters through a CC1101
serial module (433 MHz radio).

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
3. In **Configure** (the integration options), add your shutters (radio ID +
   name). You can add or remove them at any time.

Deleting a shutter **device** from the UI also removes it from the options
automatically.

## Icon (the `brand/` folder)

Since **Home Assistant 2026.3**, a custom integration can ship its own brand
images locally, without going through the
[home-assistant/brands](https://github.com/home-assistant/brands) repository.
They just have to be dropped into a `brand/` folder at the root of the
integration; Home Assistant serves them through its local API
(`/api/brands/integration/cc1101_rolling_shutter/icon.png`) and **they take
precedence** over the official CDN.

Contents of `brand/`:

| File            | Role                                    |
| --------------- | --------------------------------------- |
| `icon.png`      | 256×256 icon served by HA               |
| `icon@2x.png`   | 512×512 high-resolution variant         |
| `icon.svg`      | vector source (not served by HA)        |

The name `icon@2x.png` (with the at sign) is the one Home Assistant expects for
the 2× variant. `SVG` is not a format supported by the brand system (which only
uses PNGs): it is kept as a vector source, but Home Assistant will not display
it.

> On a version older than 2026.3, the `brand/` folder is ignored; the PNGs then
> have to be submitted to the `home-assistant/brands` repository.
> Note: HACS may show an empty icon in its own storefront (it does not read
> local images yet), which has no effect on how the integration looks in HA.

## Notes

- **RF serialization**: every command of a module goes through a shared lock —
  one transmission at a time, in order. A spacing delay
  (`RF_INTERCOMMAND_DELAY`, 0.4 s by default in `const.py`) lets each radio
  transmission finish before the next one starts, to avoid collisions when
  several shutters are operated at the same time. Set it to `0` if your
  firmware already blocks until the transmission is done. Two distinct modules
  (two entries) transmit in parallel.
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

## License

[MIT](LICENSE)
