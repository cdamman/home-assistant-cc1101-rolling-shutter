"""Compile the sketch with the real Arduino toolchain.

The firmware is C++ built by a different compiler than everything else here, so
nothing in the Python suite would notice it breaking. This drives `arduino-cli`
itself rather than approximating it, because the failure worth catching is a
preprocessing one: the Arduino builder generates a prototype for every function
and inserts them all above the first definition, which is why
`cc1101_rolling_shutter.ino` carries a forward declaration of `struct Device`.
Compiling the file as plain C++ would not reproduce that, and would pass even
with the declaration removed.

The toolchain is heavy (a board core plus the CC1101 driver), so the test skips
when it is absent; `.github/workflows/firmware.yml` is what runs it on every
change to `firmware/`. To run it locally:

    arduino-cli core install esp8266:esp8266 \\
      --additional-urls https://arduino.esp8266.com/stable/package_esp8266com_index.json
    arduino-cli lib install SmartRC-CC1101-Driver-Lib
    pytest tests/test_firmware_compiles.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest

SKETCH = (
    pathlib.Path(__file__).parent.parent / "firmware" / "cc1101_rolling_shutter"
)
# The sketch uses the D1/D4 pin macros and Serial.printf, neither of which
# exists on AVR: it has to be built for the board it actually runs on.
FQBN = os.environ.get("ARDUINO_FQBN", "esp8266:esp8266:nodemcuv2")

pytestmark = pytest.mark.firmware


def arduino_cli() -> str | None:
    """Path to arduino-cli, honouring an explicit override."""
    return os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")


def test_sketch_folder_matches_the_sketch_name() -> None:
    """The Arduino IDE only opens a sketch whose folder shares its name.

    Cheap to check and easy to break when moving files around, so it runs even
    without the toolchain.
    """
    assert SKETCH.is_dir()
    assert (SKETCH / f"{SKETCH.name}.ino").is_file()


def test_sketch_compiles() -> None:
    """The sketch builds for its target board, warnings included."""
    cli = arduino_cli()
    if cli is None:
        pytest.skip(
            "arduino-cli not installed; the firmware workflow compiles the "
            "sketch on every change to firmware/"
        )

    result = subprocess.run(
        [cli, "compile", "--fqbn", FQBN, "--warnings", "all", str(SKETCH)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(
            f"arduino-cli compile failed for {FQBN}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
