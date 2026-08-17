"""
Codec for the 868 MHz roller shutter radio protocol (2-FSK / CC1101).
Reverse engineered from captured frames. No external dependencies.

Payload is 10 bytes:

  idx 0 : rolling counter C (+1 per transmitted frame, mod 256)
  idx 1 : ID[0] XOR C
  idx 2 : ID[1] XOR C
  idx 3 : ID[2] XOR C
  idx 4 : ID[3] XOR C
  idx 5 : CMD   XOR C
  idx 6 : CMDX  XOR C      (CMDX = ROR(0xAF, 2*k), redundant copy of CMD)
  idx 7 : C                (counter repeated)
  idx 8 : (C + 7) & 0xFF
  idx 9 : sum(bytes 0..8) & 0xFF

See PROTOCOL.md for the full description.
"""

from __future__ import annotations

# --- Commands --------------------------------------------------------------
CMD_STOP = 0x01
CMD_UP = 0x02
CMD_DOWN = 0x04

# Redundant command representation carried at index 6, ROR(0xAF, 2*k).
# Only these three commands have been observed on air. A fourth button
# (pairing?) likely exists, but its encoding cannot be extrapolated: the
# mapping between the rotation index k and the command bit is already
# non-monotonic (k=0 -> bit 1, k=1 -> bit 0, k=2 -> bit 2).
_CMD_ALT = {
    CMD_STOP: 0xEB,  # ROR(0xAF, 2)
    CMD_UP: 0xAF,  # ROR(0xAF, 0)
    CMD_DOWN: 0xFA,  # ROR(0xAF, 4)
}
_ALT_CMD = {v: k for k, v in _CMD_ALT.items()}

CMD_NAMES = {CMD_STOP: "stop", CMD_UP: "open", CMD_DOWN: "close"}

FRAME_LEN = 10
COUNTER_OFFSET = 7  # byte[8] = byte[0] + 7


class DecodeError(ValueError):
    """Invalid frame (length, checksum or redundant fields inconsistent)."""


def encode(device_id, command: int, counter: int) -> bytes:
    """Build a 10-byte frame.

    device_id : iterable of 4 bytes
    command   : CMD_UP / CMD_STOP / CMD_DOWN
    counter   : rolling counter, 0..255
    """
    device_id = tuple(device_id)
    if len(device_id) != 4:
        raise ValueError("device_id must be 4 bytes")
    if command not in _CMD_ALT:
        raise ValueError(f"unknown command: {command:#04x}")

    c = counter & 0xFF
    payload = [
        c,
        device_id[0] ^ c,
        device_id[1] ^ c,
        device_id[2] ^ c,
        device_id[3] ^ c,
        command ^ c,
        _CMD_ALT[command] ^ c,
        c,
        (c + COUNTER_OFFSET) & 0xFF,
    ]
    payload.append(sum(payload) & 0xFF)
    return bytes(payload)


def encode_burst(device_id, command: int, counter: int, n: int = 4) -> list[bytes]:
    """Burst as emitted by the original remote: n frames with consecutive
    counters."""
    return [encode(device_id, command, counter + i) for i in range(n)]


def decode(frame, strict: bool = True) -> dict:
    """Decode a frame. Accepts 10 bytes, or 11 if the length byte (0x0A) is
    still present at the front."""
    b = list(frame)
    if len(b) == FRAME_LEN + 1 and b[0] == FRAME_LEN:
        b = b[1:]
    if len(b) != FRAME_LEN:
        raise DecodeError(f"length {len(b)} instead of {FRAME_LEN}")

    if sum(b[:9]) & 0xFF != b[9]:
        raise DecodeError("bad checksum")

    c = b[0]
    if strict:
        if b[7] != c:
            raise DecodeError("byte[7] != counter")
        if b[8] != (c + COUNTER_OFFSET) & 0xFF:
            raise DecodeError("byte[8] != counter + 7")

    device_id = (b[1] ^ c, b[2] ^ c, b[3] ^ c, b[4] ^ c)
    command = b[5] ^ c
    command_alt = b[6] ^ c

    if strict and _ALT_CMD.get(command_alt) != command:
        raise DecodeError(
            f"inconsistent command fields ({command:#04x} / {command_alt:#04x})"
        )

    return {
        "counter": c,
        "device_id": device_id,
        "device_id_hex": "".join(f"{x:02x}" for x in device_id),
        "command": command,
        "command_name": CMD_NAMES.get(command, f"unknown_{command:#04x}"),
    }


# --------------------------------------------------------------------------
# Debounce: a single button press produces 4 frames, often repeated. Only one
# event should reach the consumer.
# --------------------------------------------------------------------------
class BurstFilter:
    """Filters duplicate frames belonging to the same press.

    Two frames belong to the same burst when they share the shutter and the
    command, and arrive less than `window` seconds apart.
    """

    def __init__(self, window: float = 1.5):
        self.window = window
        self._last: dict[tuple, tuple[float, int]] = {}

    def accept(self, event: dict, now: float) -> bool:
        key = (event["device_id"], event["command"])
        prev = self._last.get(key)
        self._last[key] = (now, event["counter"])
        if prev is not None and now - prev[0] < self.window:
            return False
        return True


# --------------------------------------------------------------------------
# Test vectors: synthetic frames for the fictitious ID 12 34 56 00.
# --------------------------------------------------------------------------
TEST_ID = (0x12, 0x34, 0x56, 0x00)
TEST_VECTORS = {
    CMD_UP: [
        bytes.fromhex("2A381E7C2A28852A312E"),
        bytes.fromhex("2B391F7D2B29842B3235"),
        bytes.fromhex("2C3E187A2C2E832C3338"),
        bytes.fromhex("2D3F197B2D2F822D343F"),
    ],
    CMD_STOP: [
        bytes.fromhex("2A381E7C2A2BC12A316D"),
        bytes.fromhex("2B391F7D2B2AC02B3272"),
        bytes.fromhex("2C3E187A2C2DC72C337B"),
        bytes.fromhex("2D3F197B2D2CC62D3480"),
    ],
    CMD_DOWN: [
        bytes.fromhex("2A381E7C2A2ED02A317F"),
        bytes.fromhex("2B391F7D2B2FD12B3288"),
        bytes.fromhex("2C3E187A2C28D62C3385"),
        bytes.fromhex("2D3F197B2D29D72D348E"),
    ],
}


def _self_test() -> None:
    total = 0
    for cmd, frames in TEST_VECTORS.items():
        assert encode_burst(TEST_ID, cmd, 0x2A) == frames, cmd
        for f in frames:
            d = decode(f)
            assert d["device_id"] == TEST_ID, d
            assert d["command"] == cmd, d
            assert encode(TEST_ID, cmd, d["counter"]) == f
            total += 1
    print(f"self-test passed on {total} frames")


if __name__ == "__main__":
    _self_test()
