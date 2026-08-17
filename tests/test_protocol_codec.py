"""Tests for the reference codec in tools/shutter868.py.

The codec is not imported by the integration — the firmware does the encoding.
It is the executable description of PROTOCOL.md, so it is worth guarding: the
frames it produces are the fixtures anyone writing another bridge starts from.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "shutter868",
    pathlib.Path(__file__).parent.parent / "tools" / "shutter868.py",
)
shutter868 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shutter868)


def test_documented_vectors_round_trip() -> None:
    """Every published test vector encodes and decodes back to itself."""
    for command, frames in shutter868.TEST_VECTORS.items():
        assert shutter868.encode_burst(shutter868.TEST_ID, command, 0x2A) == frames
        for frame in frames:
            decoded = shutter868.decode(frame)
            assert decoded["device_id"] == shutter868.TEST_ID
            assert decoded["command"] == command
            assert (
                shutter868.encode(shutter868.TEST_ID, command, decoded["counter"])
                == frame
            )


def test_frame_layout_matches_the_documentation() -> None:
    """The counter is the XOR mask, and the integrity fields follow it."""
    frame = shutter868.encode((0x12, 0x34, 0x56, 0x00), shutter868.CMD_UP, 0x2A)

    assert len(frame) == shutter868.FRAME_LEN
    counter = frame[0]
    assert counter == 0x2A
    assert bytes(b ^ counter for b in frame[1:5]) == bytes((0x12, 0x34, 0x56, 0x00))
    assert frame[5] ^ counter == shutter868.CMD_UP
    assert frame[7] == counter
    assert frame[8] == (counter + shutter868.COUNTER_OFFSET) & 0xFF
    assert frame[9] == sum(frame[:9]) & 0xFF


def test_counter_wraps_at_256() -> None:
    """The counter is a byte; a burst crossing 0xFF stays valid."""
    frames = shutter868.encode_burst(shutter868.TEST_ID, shutter868.CMD_DOWN, 0xFE)

    assert [f[0] for f in frames] == [0xFE, 0xFF, 0x00, 0x01]
    for frame in frames:
        assert shutter868.decode(frame)["device_id"] == shutter868.TEST_ID


def test_leading_length_byte_is_accepted() -> None:
    """Frames still carrying the 0x0A length byte decode too."""
    frame = shutter868.encode(shutter868.TEST_ID, shutter868.CMD_STOP, 0x10)

    assert shutter868.decode(bytes([shutter868.FRAME_LEN]) + frame) == (
        shutter868.decode(frame)
    )


def _rechecksum(frame: bytes) -> bytes:
    """Recompute the checksum so a mutation is caught by the field it targets."""
    body = bytearray(frame[:9])
    return bytes(body) + bytes([sum(body) & 0xFF])


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda f: f[:-1], "length"),
        (lambda f: f[:9] + bytes([(f[9] + 1) & 0xFF]), "checksum"),
        # byte[7] must repeat the counter, byte[8] must be counter + 7.
        (lambda f: _rechecksum(f[:7] + bytes([(f[7] + 1) & 0xFF]) + f[8:]), "byte7"),
        (lambda f: _rechecksum(f[:8] + bytes([(f[8] + 1) & 0xFF]) + f[9:]), "byte8"),
    ],
)
def test_corrupt_frames_are_rejected(mutate, reason: str) -> None:
    """Length and checksum are enforced."""
    frame = shutter868.encode(shutter868.TEST_ID, shutter868.CMD_UP, 0x2A)

    with pytest.raises(shutter868.DecodeError):
        shutter868.decode(mutate(frame))


def test_inconsistent_redundant_fields_are_rejected_only_when_strict() -> None:
    """An unknown button fails the redundancy check but can still be inspected.

    That is how a fourth command would be captured: strict decoding refuses it,
    lenient decoding exposes the fields.
    """
    frame = bytearray(shutter868.encode(shutter868.TEST_ID, shutter868.CMD_UP, 0x2A))
    frame[6] ^= 0xFF
    frame[9] = sum(frame[:9]) & 0xFF
    frame = bytes(frame)

    with pytest.raises(shutter868.DecodeError):
        shutter868.decode(frame)

    lenient = shutter868.decode(frame, strict=False)
    assert lenient["device_id"] == shutter868.TEST_ID


def test_encode_rejects_bad_input() -> None:
    """Guard rails on the public API."""
    with pytest.raises(ValueError):
        shutter868.encode((0x12, 0x34), shutter868.CMD_UP, 0)
    with pytest.raises(ValueError):
        shutter868.encode(shutter868.TEST_ID, 0x08, 0)


def test_burst_filter_collapses_a_press() -> None:
    """The four frames of one press yield a single event."""
    filt = shutter868.BurstFilter(window=1.5)
    event = shutter868.decode(
        shutter868.encode(shutter868.TEST_ID, shutter868.CMD_UP, 0x2A)
    )

    assert filt.accept(event, now=100.0) is True
    assert filt.accept(event, now=100.2) is False
    assert filt.accept(event, now=102.0) is True
