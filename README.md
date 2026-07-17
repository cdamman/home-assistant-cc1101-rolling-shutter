# CC1101 Rolling Shutter

Home Assistant custom integration to control rolling shutters through a CC1101
serial module.

## How it works

Every shutter is exposed as a `cover` entity. On open/close, the integration
writes the command `<id> open` or `<id> close` (e.g. `4 open`) to the serial
port at 115200 baud, then waits for the module to answer `Sending`.

The state is an "assumed state" (the module reports no real state): it is
cached after each transition and **restored when Home Assistant restarts**
(`RestoreEntity`).

## Installation

1. Copy the `custom_components/cc1101_rolling_shutter/` folder into your Home
   Assistant configuration (`<config>/custom_components/`).
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration →
   "CC1101 Rolling Shutter"**.
4. Fill in the port (`/dev/ttyUSB0`) and the baud rate (`115200`).
5. In **Configure** (the integration options), add your shutters (ID + name).
   You can add or remove them at any time.

## Icon

The repository ships the CC1101 module icon: `icon.svg` (vector source) and the
`icon.png` (256×256) and `icon@2x.png` (512×512) renderings, in the formats
Home Assistant expects.

Home Assistant does not display the local images of a custom integration: the
logo comes from the official
[home-assistant/brands](https://github.com/home-assistant/brands) repository.
For the icon to show up in the UI, put both PNGs in
`custom_integrations/cc1101_rolling_shutter/` of that repository (through a
pull request), or wait for them to be merged. In the meantime the icon stays
shipped alongside the code.

## Notes

- The serial port is shared by every shutter and protected by a lock: commands
  never overlap.
- Command terminator: `\n` by default (see `COMMAND_TERMINATOR` in `const.py`).
  Set it to `""` if your firmware does not expect one.
- If the response does not contain `Sending`, the service call fails and the
  state is left unchanged.
- Make sure the Home Assistant user can access the port (`/dev/ttyUSB0`, group
  `dialout`).
