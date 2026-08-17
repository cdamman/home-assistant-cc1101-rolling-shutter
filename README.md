# CC1101 Rolling Shutter

[![Tests](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/tests.yml)
[![Validate](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml/badge.svg)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/cdamman/home-assistant-cc1101-rolling-shutter?display_name=tag&sort=semver)](https://github.com/cdamman/home-assistant-cc1101-rolling-shutter/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant custom integration to control rolling shutters through a CC1101
serial module (868 MHz radio).

The repository holds every half of the setup: the Home Assistant integration
under `custom_components/`, the [firmware](#firmware) that runs on the
Arduino-compatible board driving the CC1101 under `firmware/`, and the
[reverse-engineered protocol](PROTOCOL.md) the shutters speak, with a reference
codec in `tools/shutter868.py`.

Shutters are addressed by their **4-byte radio ID**, and the firmware decodes
every frame on the air — so shutters are **discovered automatically**, and
operating one from its original remote is **reflected in Home Assistant**.

## How it works

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

Three GitHub workflows run on pushes and pull requests:

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
  `arduino-cli` is installed, and skips otherwise.

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
