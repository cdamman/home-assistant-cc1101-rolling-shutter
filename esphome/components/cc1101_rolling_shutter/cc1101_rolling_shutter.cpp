#include "cc1101_rolling_shutter.h"
#include "shutter_cover.h"

#include "esphome/core/log.h"

#ifdef USE_ARDUINO
#include <ELECHOUSE_CC1101_SRC_DRV.h>
#endif

namespace esphome {
namespace cc1101_rolling_shutter {

static const char *const TAG = "cc1101_rolling_shutter";

// 152 bits at 9.57 kBaud is 15.9 ms on air; the driver wants a whole number.
static const uint16_t FRAME_AIR_TIME_MS = 16;

// How often the SPI link is re-checked. Rare while it answers — one register
// read, but nothing is going to unplug itself often — and brisk while it does
// not, so re-seating a module is reflected without a reboot.
static const uint32_t RADIO_CHECK_MS = 60000;
static const uint32_t RADIO_RETRY_MS = 5000;

std::string key_to_string(uint32_t key) {
  char buffer[9];
  snprintf(buffer, sizeof(buffer), "%08x", key);
  return std::string(buffer);
}

void CC1101RollingShutter::setup() {
  // The id is what the YAML already says; publishing it is what lets you read
  // it back from Home Assistant, next to the shutter it belongs to, without
  // going to find the configuration. It never changes, so once is enough.
#ifdef USE_TEXT_SENSOR
  for (auto &slot : this->slots_) {
    if (slot.id_sensor != nullptr)
      slot.id_sensor->publish_state(key_to_string(slot.key));
  }
#endif

#ifdef USE_ARDUINO
  // Before Init(), which is what configures the bus from them. Left alone, the
  // driver picks its own defaults for the platform.
  if (this->custom_spi_pins_)
    ELECHOUSE_cc1101.setSpiPin(this->sck_pin_, this->miso_pin_, this->mosi_pin_,
                               this->cs_pin_);

  this->set_radio_ok_(this->bring_up_radio_());
#else
  ESP_LOGE(TAG, "cc1101_rolling_shutter needs the Arduino framework");
  this->mark_failed();
#endif
}

#ifdef USE_ARDUINO
bool CC1101RollingShutter::bring_up_radio_() {
  ELECHOUSE_cc1101.Init();

  // After Init(), not before: the presence check reads a status register, and
  // until Init() has run the driver has not configured the SPI pins to read it
  // through. Asking first is what the standalone sketch does, and it is why it
  // sometimes reports a connection error on a perfectly good module.
  if (!ELECHOUSE_cc1101.getCC1101())
    return false;

  // Same configuration the standalone sketch used, which is the one known to
  // work against these shutters. See PROTOCOL.md §1 for where each value comes
  // from, and the README for how to re-derive them for different hardware.
  // Re-applied on every bring-up: Init() resets the chip to its own defaults.
  ELECHOUSE_cc1101.setGDO0(this->gdo0_pin_);
  ELECHOUSE_cc1101.setCCMode(1);
  ELECHOUSE_cc1101.setModulation(0);  // 2-FSK
  ELECHOUSE_cc1101.setMHZ(this->frequency_);
  ELECHOUSE_cc1101.setDeviation(this->deviation_);
  ELECHOUSE_cc1101.setChannel(0);
  ELECHOUSE_cc1101.setChsp(199.95);
  ELECHOUSE_cc1101.setRxBW(this->rx_bandwidth_);
  ELECHOUSE_cc1101.setDRate(this->data_rate_);
  ELECHOUSE_cc1101.setPA(this->output_power_);
  // 16/16 sync bits: fewer false syncs. Drop to 1 if presses get missed.
  ELECHOUSE_cc1101.setSyncMode(2);
  ELECHOUSE_cc1101.setSyncWord(this->sync_high_, this->sync_low_);
  ELECHOUSE_cc1101.setAdrChk(0);
  ELECHOUSE_cc1101.setAddr(0);
  ELECHOUSE_cc1101.setWhiteData(0);
  ELECHOUSE_cc1101.setPktFormat(0);
  ELECHOUSE_cc1101.setLengthConfig(0);  // fixed length
  ELECHOUSE_cc1101.setPacketLength(FRAME_LEN + 1);
  ELECHOUSE_cc1101.setCrc(0);
  ELECHOUSE_cc1101.setCRC_AF(0);
  ELECHOUSE_cc1101.setDcFilterOff(0);
  ELECHOUSE_cc1101.setManchester(0);
  ELECHOUSE_cc1101.setFEC(0);
  ELECHOUSE_cc1101.setPRE(3);  // 6 preamble bytes
  ELECHOUSE_cc1101.setPQT(0);
  ELECHOUSE_cc1101.setAppendStatus(0);

  ELECHOUSE_cc1101.SetRx();
  return true;
}
#endif

/// Record the state of the SPI link, announcing it only when it changes.
///
/// Deliberately not mark_failed(): a module that is loose, unpowered or wired
/// to the wrong pin is a recoverable condition, and a failed component stops
/// getting its loop() called — which is exactly when this diagnostic would
/// have to report. An error status instead, and the radio is retried.
void CC1101RollingShutter::set_radio_ok_(bool ok) {
  const bool changed = !this->radio_state_known_ || ok != this->radio_ok_;
  this->radio_ok_ = ok;
  this->radio_state_known_ = true;

  if (changed) {
    if (ok) {
      ESP_LOGI(TAG, "CC1101 answering on SPI, listening");
      this->status_clear_error();
    } else {
      ESP_LOGE(TAG, "No CC1101 answering on the SPI bus — check wiring and power");
      // No message: the overload that takes one wants a LogString and is
      // recent, and the line above already says it. This one has been there
      // all along, so the component builds against older ESPHome too.
      this->status_set_error();
    }
  }

#ifdef USE_BINARY_SENSOR
  if (this->spi_sensor_ != nullptr)
    this->spi_sensor_->publish_state(ok);
#endif
}

void CC1101RollingShutter::dump_config() {
  ESP_LOGCONFIG(TAG, "CC1101 Shutter:");
  ESP_LOGCONFIG(TAG, "  Frequency: %.3f MHz", this->frequency_);
  ESP_LOGCONFIG(TAG, "  Deviation: %.2f kHz", this->deviation_);
  ESP_LOGCONFIG(TAG, "  Data rate: %.2f kBaud", this->data_rate_);
  ESP_LOGCONFIG(TAG, "  Sync word: 0x%02x 0x%02x", this->sync_high_, this->sync_low_);
  ESP_LOGCONFIG(TAG, "  GDO0 pin: GPIO%u", this->gdo0_pin_);
  if (this->custom_spi_pins_) {
    ESP_LOGCONFIG(TAG, "  SPI: SCK GPIO%u, MISO GPIO%u, MOSI GPIO%u, CS GPIO%u",
                  this->sck_pin_, this->miso_pin_, this->mosi_pin_, this->cs_pin_);
  } else {
    ESP_LOGCONFIG(TAG, "  SPI: driver defaults for this platform");
  }
  ESP_LOGCONFIG(TAG, "  Burst: %u frames x %u repeats", this->frames_per_press_,
                this->repeats_);
  ESP_LOGCONFIG(TAG, "  Shutters: %u", (unsigned) this->slots_.size());
  ESP_LOGCONFIG(TAG, "  Module: %s", this->radio_ok_ ? "answering on SPI" : "NOT FOUND");
#ifdef USE_BINARY_SENSOR
  LOG_BINARY_SENSOR("  ", "CC1101: SPI Link", this->spi_sensor_);
#endif
}

ShutterSlot *CC1101RollingShutter::slot_for_(uint32_t key) {
  for (auto &slot : this->slots_) {
    if (slot.key == key)
      return &slot;
  }
  ShutterSlot slot;
  slot.key = key;
  this->slots_.push_back(slot);
  return &this->slots_.back();
}

void CC1101RollingShutter::register_cover(uint32_t key, CC1101RollingShutterCover *cover) {
  this->slot_for_(key)->cover = cover;
}

#ifdef USE_TEXT_SENSOR
void CC1101RollingShutter::set_id_sensor(uint32_t key, text_sensor::TextSensor *sensor) {
  this->slot_for_(key)->id_sensor = sensor;
}
#endif

#ifdef USE_SENSOR
void CC1101RollingShutter::set_counter_sensor(uint32_t key, sensor::Sensor *sensor) {
  this->slot_for_(key)->counter_sensor = sensor;
}

void CC1101RollingShutter::set_rssi_sensor(uint32_t key, sensor::Sensor *sensor) {
  this->slot_for_(key)->rssi_sensor = sensor;
}
#endif

void CC1101RollingShutter::publish_counter_(ShutterSlot *slot) {
#ifdef USE_SENSOR
  if (slot->counter_sensor != nullptr)
    slot->counter_sensor->publish_state(slot->counter);
#else
  (void) slot;
#endif
}

void CC1101RollingShutter::send(uint32_t key, uint8_t command) {
#ifdef USE_ARDUINO
  if (!this->radio_ok_) {
    ESP_LOGW(TAG, "Not sending to %s: no CC1101 on the SPI bus",
             key_to_string(key).c_str());
    return;
  }

  ShutterSlot *slot = this->slot_for_(key);
  uint8_t id[ID_LEN];
  key_to_id(key, id);

  // Continue this shutter's sequence. Nothing enforces monotonicity on the
  // receiving end, so starting from 0 after a reboot is harmless.
  const uint8_t base = slot->counter + 1;
  uint8_t frame[FRAME_LEN];

  for (uint8_t repeat = 0; repeat < this->repeats_; repeat++) {
    for (uint8_t index = 0; index < this->frames_per_press_; index++) {
      build_frame(id, command, (uint8_t) (base + index), frame);
      ELECHOUSE_cc1101.SendData(frame, FRAME_LEN, 2 * FRAME_AIR_TIME_MS);
    }
  }

  slot->counter = (uint8_t) (base + this->frames_per_press_ - 1);
  slot->counter_known = true;
  ELECHOUSE_cc1101.SetRx();

  ESP_LOGD(TAG, "Sent 0x%02x to %s, counter now %u", command, key_to_string(key).c_str(),
           slot->counter);
  this->publish_counter_(slot);
#else
  (void) key;
  (void) command;
#endif
}

void CC1101RollingShutter::loop() {
#ifdef USE_ARDUINO
  const uint32_t now = millis();
  const uint32_t interval = this->radio_ok_ ? RADIO_CHECK_MS : RADIO_RETRY_MS;
  if (now - this->last_probe_ >= interval) {
    this->last_probe_ = now;
    if (this->radio_ok_) {
      // Reading the version register does not disturb reception, so a live
      // module can be checked on without a gap in coverage.
      this->set_radio_ok_(ELECHOUSE_cc1101.getCC1101());
    } else {
      // Full bring-up: a module that has just been plugged in needs its
      // registers written before it is any use.
      this->set_radio_ok_(this->bring_up_radio_());
    }
  }

  if (!this->radio_ok_)
    return;

  if (!ELECHOUSE_cc1101.CheckRxFifo(FRAME_AIR_TIME_MS))
    return;

  const int rssi = ELECHOUSE_cc1101.getRssi();
  // Always drain the FIFO, even for a frame about to be discarded: leaving it
  // full would stall reception.
  const int len = ELECHOUSE_cc1101.ReceiveData(this->rx_buffer_);
  if (len <= 0)
    return;

  // Anything this faint is noise that happened to trip the sync detector;
  // dropping it keeps the unknown-frame warning meaningful.
  if (rssi < this->rssi_threshold_)
    return;

  this->handle_frame_(this->rx_buffer_, len, rssi);
#endif
}

void CC1101RollingShutter::handle_frame_(const uint8_t *frame, int len, int rssi) {
  uint8_t id[ID_LEN], command, counter;
  if (!parse_frame(frame, (size_t) len, id, &command, &counter)) {
    // Noise, or the fourth button nobody has captured yet. Dump it unmasked
    // when it is structurally ours, which is what identifying it needs.
    if (checksum_ok(frame, (size_t) len)) {
      char unmasked[2 * FRAME_LEN + 1];
      for (size_t i = 0; i < FRAME_LEN; i++)
        snprintf(unmasked + 2 * i, 3, "%02x", frame[i] ^ frame[0]);
      ESP_LOGW(TAG, "Unrecognised frame (rssi %d), unmasked: %s", rssi, unmasked);
    }
    return;
  }

  const uint32_t key = id_to_key(id);
  const uint32_t now = millis();

  // One press is 4 to 16 frames; only the first should move anything.
  bool known_shutter = false;
  bool same_press = false;
  for (size_t i = 0; i < this->last_press_keys_.size(); i++) {
    if (this->last_press_keys_[i] != key)
      continue;
    known_shutter = true;
    same_press = this->last_press_commands_[i] == command &&
                 (now - this->last_press_times_[i]) < this->burst_window_;
    this->last_press_times_[i] = now;
    this->last_press_commands_[i] = command;
    break;
  }
  if (!known_shutter) {
    this->last_press_keys_.push_back(key);
    this->last_press_times_.push_back(now);
    this->last_press_commands_.push_back(command);
  }

  // Resynchronise on every frame of the burst, each one having advanced the
  // counter, and only then decide whether this frame is worth acting on.
  ShutterSlot *slot = this->slot_for_(key);
  slot->counter = counter;
  slot->counter_known = true;
  if (same_press)
    return;

  ESP_LOGD(TAG, "Heard 0x%02x from %s (counter %u, rssi %d)", command,
           key_to_string(key).c_str(), counter, rssi);
  this->publish_counter_(slot);
#ifdef USE_SENSOR
  if (slot->rssi_sensor != nullptr)
    slot->rssi_sensor->publish_state(rssi);
#else
  (void) rssi;
#endif
  this->report_heard_(key, slot->cover != nullptr);
  if (slot->cover != nullptr)
    slot->cover->on_air_command(command);
}

void CC1101RollingShutter::report_heard_(uint32_t key, bool configured) {
  // Every shutter heard, not only the unconfigured ones: the sensor answers
  // "which shutter was that?", and the answer is just as useful when it is one
  // you already have — checking that the right id reaches the node is the
  // first thing anyone does when a shutter does not respond.
#ifdef USE_TEXT_SENSOR
  if (this->discovered_sensor_ != nullptr)
    this->discovered_sensor_->publish_state(key_to_string(key));
#endif

  if (configured)
    return;

  // No cover for it: ours but unconfigured, or a neighbour's. Entities cannot
  // be created at runtime, so say once per shutter what to do about it.
  if (this->has_unknown_ && this->last_unknown_key_ == key)
    return;
  this->has_unknown_ = true;
  this->last_unknown_key_ = key;
  ESP_LOGI(TAG, "Heard unconfigured shutter %s — add it to your YAML to control it",
           key_to_string(key).c_str());
}

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
