// 868 MHz roller shutter frame codec.
//
// Deliberately free of Arduino, ESPHome and even <string>: nothing here touches
// hardware, so the same header is compiled by the host test in
// tests/firmware/test_protocol.cpp and checked against the vectors published in
// PROTOCOL.md. The radio layer lives next door in cc1101_rolling_shutter.cpp.
//
// Frame layout (see PROTOCOL.md §2): the rolling counter is itself the XOR mask
// over the identifier and command fields.
//
//   0    1    2    3    4    5    6    7    8    9
// ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
// │ C  │ID0 │ID1 │ID2 │ID3 │CMD │CMDX│ C  │C+7 │SUM │
// └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
//        └──────── all XOR C ─────────┘
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace esphome {
namespace cc1101_rolling_shutter {

static const uint8_t FRAME_LEN = 10;
static const uint8_t ID_LEN = 4;
// byte[8] = byte[0] + 7. The offset is structural: constant across every frame
// ever captured. Why it is 7 is unknown (PROTOCOL.md §8).
static const uint8_t COUNTER_OFFSET = 7;
// byte[6] = ROR(0xAF, 2 * k), a redundant encoding of the command.
static const uint8_t CMD_ALT_BASE = 0xAF;

// Only these three have been observed on air. A fourth button (pairing?) very
// likely exists, but its encoding cannot be extrapolated: the mapping between
// the rotation index k and the command bit is already non-monotonic
// (k=0 -> bit 1, k=1 -> bit 0, k=2 -> bit 2).
static const uint8_t CMD_STOP = 0x01;
static const uint8_t CMD_UP = 0x02;
static const uint8_t CMD_DOWN = 0x04;

/// Redundant counterpart of a command, or 0 if the command is not one of ours.
inline uint8_t cmd_alt(uint8_t cmd) {
  uint8_t k;  // rotation = 2 * button index
  switch (cmd) {
    case CMD_UP:
      k = 0;
      break;
    case CMD_STOP:
      k = 2;
      break;
    case CMD_DOWN:
      k = 4;
      break;
    default:
      return 0;
  }
  return (uint8_t) ((CMD_ALT_BASE >> k) | (CMD_ALT_BASE << (8 - k)));
}

/// Build one frame into `out`, which must hold FRAME_LEN bytes.
inline void build_frame(const uint8_t id[ID_LEN], uint8_t cmd, uint8_t counter, uint8_t *out) {
  out[0] = counter;
  out[1] = id[0] ^ counter;
  out[2] = id[1] ^ counter;
  out[3] = id[2] ^ counter;
  out[4] = id[3] ^ counter;
  out[5] = cmd ^ counter;
  out[6] = cmd_alt(cmd) ^ counter;
  out[7] = counter;
  out[8] = counter + COUNTER_OFFSET;

  uint8_t sum = 0;
  for (uint8_t i = 0; i < 9; i++)
    sum += out[i];
  out[9] = sum;
}

/// Plain sum over bytes 0..8, as carried in byte 9.
inline bool checksum_ok(const uint8_t *frame, size_t len) {
  if (len != FRAME_LEN)
    return false;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < 9; i++)
    sum += frame[i];
  return sum == frame[9];
}

/// Decode a frame, rejecting anything that fails an integrity check.
///
/// A frame that is the right length and checksums correctly but fails the
/// command redundancy check is very likely our protocol carrying an unknown
/// button — the caller is expected to surface it rather than drop it silently.
inline bool parse_frame(const uint8_t *frame, size_t len, uint8_t id[ID_LEN], uint8_t *cmd,
                        uint8_t *counter) {
  if (!checksum_ok(frame, len))
    return false;

  const uint8_t c = frame[0];
  if (frame[7] != c)
    return false;
  if (frame[8] != (uint8_t) (c + COUNTER_OFFSET))
    return false;

  const uint8_t command = frame[5] ^ c;
  if ((uint8_t) (frame[6] ^ c) != cmd_alt(command))
    return false;

  for (uint8_t i = 0; i < ID_LEN; i++)
    id[i] = frame[i + 1] ^ c;
  *cmd = command;
  *counter = c;
  return true;
}

/// Pack a 4-byte identifier into the 32-bit key used to index shutters.
inline uint32_t id_to_key(const uint8_t id[ID_LEN]) {
  return ((uint32_t) id[0] << 24) | ((uint32_t) id[1] << 16) | ((uint32_t) id[2] << 8) |
         (uint32_t) id[3];
}

/// Inverse of id_to_key.
inline void key_to_id(uint32_t key, uint8_t id[ID_LEN]) {
  id[0] = (uint8_t) (key >> 24);
  id[1] = (uint8_t) (key >> 16);
  id[2] = (uint8_t) (key >> 8);
  id[3] = (uint8_t) key;
}

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
