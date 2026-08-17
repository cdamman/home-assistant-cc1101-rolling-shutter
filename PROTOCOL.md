# 868 MHz roller shutter protocol (reverse engineered)

Reverse engineered from 60 captured frames (5 shutters × 3 commands × 4 frames).
Every rule below holds on 60/60 frames, and re-encoding from the decoded fields
reproduces the original bytes exactly.

The manufacturer is unknown — the motors are generic Chinese tubular motors.
If you own hardware speaking this protocol, please open an issue with the brand
so we can name it properly.

## 1. Physical layer

| Parameter | Value |
|---|---|
| Frequency | 868.027 MHz (a −83 kHz offset is applied to the CC1101) |
| Modulation | 2-FSK, 55 kHz deviation |
| Data rate | 9.57 kBaud |
| Preamble | 6 × `0xAA` |
| Sync word | `0x4B 0xD4` |
| Length byte | `0x0A` (fixed length mode) |
| Payload | 10 bytes |
| Hardware CRC | none — an application checksum is used instead |
| Total | 19 bytes = 152 bits ≈ 15.9 ms |

## 2. Frame structure

The core trick: **the rolling counter is itself the XOR mask** for the payload
fields. This is obfuscation, not encryption — no KeeLoq, no secret key.

```
index:    0    1    2    3    4    5    6    7    8    9
        ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
        │ C  │ID0 │ID1 │ID2 │ID3 │CMD │CMDX│ C  │C+7 │SUM │
        └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
                └──────── all XOR C ─────────┘
```

| Index | Content | Notes |
|---|---|---|
| 0 | `C` | rolling counter, +1 per transmitted frame, mod 256 |
| 1–4 | `ID[0..3] ^ C` | 4-byte shutter identifier |
| 5 | `CMD ^ C` | command |
| 6 | `CMDX ^ C` | redundant copy of the command |
| 7 | `C` | counter repeated (integrity check) |
| 8 | `(C + 7) & 0xFF` | counter offset by 7 (integrity check) |
| 9 | `Σ(bytes 0..8) & 0xFF` | checksum, plain sum |

### Decoding

```
C   = frame[0]
ID  = frame[1..4] XOR C
CMD = frame[5]    XOR C
```

## 3. Commands

| Command | `CMD` (idx 5) | `CMDX` (idx 6) |
|---|---|---|
| STOP | `0x01` | `0xEB` |
| UP | `0x02` | `0xAF` |
| DOWN | `0x04` | `0xFA` |

`CMD` is one-hot encoded: bit 0 = stop, bit 1 = up, bit 2 = down.

`CMDX` follows `ROR(0xAF, 2·k)` where k is the rotation index — up = 0,
stop = 1, down = 2.

A fourth button almost certainly exists (pairing), but its encoding **cannot be
extrapolated**: the mapping between the rotation index k and the command bit is
already non-monotonic (k=0 → bit 1, k=1 → bit 0, k=2 → bit 2), so nothing
indicates that k=3 would pair with bit 3. Both values have to be captured off
the air.

Both `CMD` and `CMDX` are **identical across all shutters**: they are protocol
constants, not device-specific data.

## 4. Device identifiers

Each motor is bound to a 4-byte identifier. Treat it as an opaque value: read it
off the air with the sniffer and copy it into your configuration.

In the captured set the first byte was always `0x09` or `0x0A` and the last one
`0x00` or `0x01`, which suggests roughly a 20-bit serial number plus a small
trailing field (channel?). This has no practical impact on decoding.

## 5. Rolling counter

The counter belongs to the **remote**, not to the shutter: all channels of one
remote share a single counter. In the captured set the values formed one
increasing sequence spanning all five shutters, in capture order — a single
multi-channel remote.

Each button press emits **4 frames with consecutive counters** (`n`, `n+1`,
`n+2`, `n+3`). Remotes repeat the burst while the button is held.

Frames only carry the shutter ID, never a remote ID, so remotes cannot be told
apart over the air. An implementation should therefore keep **one counter per
ID**: a single global counter breaks as soon as a second remote is in use, since
each remote maintains its own sequence. IDs belonging to the same remote will
drift apart only through the implementation's own transmissions, and each is
resynchronised the next time that shutter's button is pressed.

Replaying previously captured codes still operates the motors, so receivers do
**not** enforce strict counter monotonicity. Resuming from the last counter heard
on the air is still preferable, to stay aligned with the physical remotes.

## 6. Example frames

Synthetic vectors generated for the fictitious ID `12 34 56 00`, counter
starting at `0x2A`. Useful as unit-test fixtures.

| Command | Frames |
|---|---|
| UP | `2A 38 1E 7C 2A 28 85 2A 31 2E`<br>`2B 39 1F 7D 2B 29 84 2B 32 35`<br>`2C 3E 18 7A 2C 2E 83 2C 33 38`<br>`2D 3F 19 7B 2D 2F 82 2D 34 3F` |
| STOP | `2A 38 1E 7C 2A 2B C1 2A 31 6D`<br>`2B 39 1F 7D 2B 2A C0 2B 32 72`<br>`2C 3E 18 7A 2C 2D C7 2C 33 7B`<br>`2D 3F 19 7B 2D 2C C6 2D 34 80` |
| DOWN | `2A 38 1E 7C 2A 2E D0 2A 31 7F`<br>`2B 39 1F 7D 2B 2F D1 2B 32 88`<br>`2C 3E 18 7A 2C 28 D6 2C 33 85`<br>`2D 3F 19 7B 2D 29 D7 2D 34 8E` |

## 7. Security

The protocol offers no real protection: plaintext counter, trivially reversible
XOR mask, sum checksum, no authentication. Anyone in radio range can recover a
shutter ID and forge valid frames. This is unremarkable for this class of
hardware, but worth stating explicitly.

## 8. Open questions

- The exact role of byte 8 (`C + 7`). The offset of 7 is constant across all 60
  frames, including across separate capture sessions, so it is structural — but
  the reason is unknown.
- Internal structure of the ID (serial number + channel?).
- Encoding of the fourth button (pairing?): both its `CMD` bit and its `CMDX`
  value are unknown and cannot be derived from the three observed commands.
- Whether a remote ID exists anywhere in the frame, which would allow grouping
  the channels of one remote behind a single counter.
- Long-press behaviour (longer burst, or a different command?).

The sketch prints any non-conforming frame in `raw` mode, which is the easiest
way to settle these questions by pressing the uncaptured buttons.
