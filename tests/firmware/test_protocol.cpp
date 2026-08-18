// Host test for esphome/components/cc1101_rolling_shutter/protocol.h.
//
// The codec is the one piece of the ESPHome component that can be verified
// without hardware or a cross-compiler, and it is the piece where a mistake is
// silent: a wrong byte does not fail to build, it just fails to move a shutter.
// So it is checked against the same vectors that PROTOCOL.md publishes and that
// tools/shutter868.py is tested against — three independent implementations of
// one specification, pinned to the same numbers.
//
//   c++ -std=c++17 -Wall -Wextra -Werror
//       -o test_protocol tests/firmware/test_protocol.cpp && ./test_protocol
#include "../../esphome/components/cc1101_rolling_shutter/protocol.h"

#include <cstdio>
#include <cstring>
#include <vector>

using namespace esphome::cc1101_rolling_shutter;

static int failures = 0;
static int checks = 0;

#define CHECK(cond, ...) \
  do { \
    checks++; \
    if (!(cond)) { \
      failures++; \
      std::printf("FAIL %s:%d: ", __FILE__, __LINE__); \
      std::printf(__VA_ARGS__); \
      std::printf("\n"); \
    } \
  } while (0)

namespace {

const uint8_t TEST_ID[ID_LEN] = {0x12, 0x34, 0x56, 0x00};

struct Vector {
  uint8_t command;
  const char *name;
  uint8_t frames[4][FRAME_LEN];
};

// PROTOCOL.md §6, for the fictitious ID 12 34 56 00 starting at counter 0x2A.
const Vector VECTORS[] = {
    {CMD_UP,
     "up",
     {{0x2A, 0x38, 0x1E, 0x7C, 0x2A, 0x28, 0x85, 0x2A, 0x31, 0x2E},
      {0x2B, 0x39, 0x1F, 0x7D, 0x2B, 0x29, 0x84, 0x2B, 0x32, 0x35},
      {0x2C, 0x3E, 0x18, 0x7A, 0x2C, 0x2E, 0x83, 0x2C, 0x33, 0x38},
      {0x2D, 0x3F, 0x19, 0x7B, 0x2D, 0x2F, 0x82, 0x2D, 0x34, 0x3F}}},
    {CMD_STOP,
     "stop",
     {{0x2A, 0x38, 0x1E, 0x7C, 0x2A, 0x2B, 0xC1, 0x2A, 0x31, 0x6D},
      {0x2B, 0x39, 0x1F, 0x7D, 0x2B, 0x2A, 0xC0, 0x2B, 0x32, 0x72},
      {0x2C, 0x3E, 0x18, 0x7A, 0x2C, 0x2D, 0xC7, 0x2C, 0x33, 0x7B},
      {0x2D, 0x3F, 0x19, 0x7B, 0x2D, 0x2C, 0xC6, 0x2D, 0x34, 0x80}}},
    {CMD_DOWN,
     "down",
     {{0x2A, 0x38, 0x1E, 0x7C, 0x2A, 0x2E, 0xD0, 0x2A, 0x31, 0x7F},
      {0x2B, 0x39, 0x1F, 0x7D, 0x2B, 0x2F, 0xD1, 0x2B, 0x32, 0x88},
      {0x2C, 0x3E, 0x18, 0x7A, 0x2C, 0x28, 0xD6, 0x2C, 0x33, 0x85},
      {0x2D, 0x3F, 0x19, 0x7B, 0x2D, 0x29, 0xD7, 0x2D, 0x34, 0x8E}}},
};

void hex(const uint8_t *frame, char *out) {
  for (size_t i = 0; i < FRAME_LEN; i++)
    std::sprintf(out + 2 * i, "%02x", frame[i]);
}

void test_documented_vectors() {
  for (const Vector &vector : VECTORS) {
    for (uint8_t i = 0; i < 4; i++) {
      uint8_t built[FRAME_LEN];
      build_frame(TEST_ID, vector.command, (uint8_t) (0x2A + i), built);

      char got[2 * FRAME_LEN + 1], want[2 * FRAME_LEN + 1];
      hex(built, got);
      hex(vector.frames[i], want);
      CHECK(std::memcmp(built, vector.frames[i], FRAME_LEN) == 0,
            "%s frame %u: built %s, expected %s", vector.name, i, got, want);
    }
  }
}

void test_round_trip() {
  for (const Vector &vector : VECTORS) {
    for (const auto &frame : vector.frames) {
      uint8_t id[ID_LEN], cmd, counter;
      CHECK(parse_frame(frame, FRAME_LEN, id, &cmd, &counter), "%s: frame rejected",
            vector.name);
      CHECK(std::memcmp(id, TEST_ID, ID_LEN) == 0, "%s: wrong id", vector.name);
      CHECK(cmd == vector.command, "%s: wrong command 0x%02x", vector.name, cmd);

      uint8_t rebuilt[FRAME_LEN];
      build_frame(id, cmd, counter, rebuilt);
      CHECK(std::memcmp(rebuilt, frame, FRAME_LEN) == 0, "%s: re-encode differs",
            vector.name);
    }
  }
}

void test_counter_wraps() {
  // The counter is a byte; a burst crossing 0xFF must stay decodable.
  const uint8_t counters[] = {0xFE, 0xFF, 0x00, 0x01};
  for (uint8_t base : counters) {
    uint8_t frame[FRAME_LEN];
    build_frame(TEST_ID, CMD_DOWN, base, frame);
    CHECK(frame[0] == base, "counter byte 0x%02x lost", base);
    CHECK(frame[8] == (uint8_t) (base + COUNTER_OFFSET), "byte[8] wrong at 0x%02x", base);

    uint8_t id[ID_LEN], cmd, counter;
    CHECK(parse_frame(frame, FRAME_LEN, id, &cmd, &counter), "wrap 0x%02x rejected", base);
    CHECK(counter == base, "wrap 0x%02x decoded as 0x%02x", base, counter);
  }
}

void test_integrity_checks() {
  uint8_t id[ID_LEN], cmd, counter;
  uint8_t frame[FRAME_LEN];
  build_frame(TEST_ID, CMD_UP, 0x2A, frame);

  CHECK(!parse_frame(frame, FRAME_LEN - 1, id, &cmd, &counter), "short frame accepted");
  CHECK(!parse_frame(frame, FRAME_LEN + 1, id, &cmd, &counter), "long frame accepted");

  // Each mutation is re-checksummed, so the field it targets is what rejects it.
  const size_t guarded[] = {7, 8};
  for (size_t index : guarded) {
    uint8_t bad[FRAME_LEN];
    std::memcpy(bad, frame, FRAME_LEN);
    bad[index]++;
    uint8_t sum = 0;
    for (uint8_t i = 0; i < 9; i++)
      sum += bad[i];
    bad[9] = sum;
    CHECK(!parse_frame(bad, FRAME_LEN, id, &cmd, &counter), "byte[%zu] not checked", index);
  }

  uint8_t bad_sum[FRAME_LEN];
  std::memcpy(bad_sum, frame, FRAME_LEN);
  bad_sum[9]++;
  CHECK(!parse_frame(bad_sum, FRAME_LEN, id, &cmd, &counter), "bad checksum accepted");
}

void test_unknown_command_is_rejected_but_checksums() {
  // How a fourth button shows up: structurally valid, redundancy mismatched.
  uint8_t frame[FRAME_LEN];
  build_frame(TEST_ID, CMD_UP, 0x2A, frame);
  frame[6] ^= 0xFF;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < 9; i++)
    sum += frame[i];
  frame[9] = sum;

  CHECK(checksum_ok(frame, FRAME_LEN), "unknown button should still checksum");
  uint8_t id[ID_LEN], cmd, counter;
  CHECK(!parse_frame(frame, FRAME_LEN, id, &cmd, &counter),
        "inconsistent command fields accepted");
}

void test_cmd_alt_matches_the_specification() {
  CHECK(cmd_alt(CMD_UP) == 0xAF, "cmd_alt(up) = 0x%02x", cmd_alt(CMD_UP));
  CHECK(cmd_alt(CMD_STOP) == 0xEB, "cmd_alt(stop) = 0x%02x", cmd_alt(CMD_STOP));
  CHECK(cmd_alt(CMD_DOWN) == 0xFA, "cmd_alt(down) = 0x%02x", cmd_alt(CMD_DOWN));
  CHECK(cmd_alt(0x08) == 0, "an unknown command must have no counterpart");
}

void test_id_key_round_trip() {
  const uint32_t key = id_to_key(TEST_ID);
  CHECK(key == 0x12345600u, "id_to_key = 0x%08x", key);
  uint8_t back[ID_LEN];
  key_to_id(key, back);
  CHECK(std::memcmp(back, TEST_ID, ID_LEN) == 0, "key_to_id did not round-trip");
}

}  // namespace

int main() {
  test_documented_vectors();
  test_round_trip();
  test_counter_wraps();
  test_integrity_checks();
  test_unknown_command_is_rejected_but_checksums();
  test_cmd_alt_matches_the_specification();
  test_id_key_round_trip();

  std::printf("%d checks, %d failures\n", checks, failures);
  return failures == 0 ? 0 : 1;
}
