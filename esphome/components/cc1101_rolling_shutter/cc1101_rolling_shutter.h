#pragma once

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/helpers.h"

#include "protocol.h"

#include <vector>

#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif
#ifdef USE_BINARY_SENSOR
#include "esphome/components/binary_sensor/binary_sensor.h"
#endif

namespace esphome {
namespace cc1101_rolling_shutter {

/// Size of the receive buffer — every byte a length field can ask for.
///
/// The driver's ReceiveData() reads the packet's first byte as a length and
/// then writes that many bytes into the buffer it was given, with no cap of
/// its own. A valid frame says 10, but noise that trips the sync detector says
/// whatever the air handed it, up to 255. Anything smaller here is a buffer
/// overflow waiting for a quiet afternoon; on the stack it was a crash inside
/// SpiReadBurstReg, the loop having overwritten its own arguments.
static const size_t RX_BUFFER_LEN = 256;
static_assert(RX_BUFFER_LEN > UINT8_MAX,
              "the length field is a byte, so the buffer must cover every value it can hold");

class CC1101RollingShutterCover;

/// Everything the hub knows about one shutter.
///
/// The rolling counter belongs to the *remote*, not to the shutter, but frames
/// carry only the shutter id, so remotes cannot be told apart on the air. One
/// counter per id is therefore the right granularity — see PROTOCOL.md §5. It
/// is deliberately not persisted: receivers do not enforce monotonicity, so a
/// reboot costs nothing, and flash writes on every command would not.
struct ShutterSlot {
  uint32_t key{0};
  uint8_t counter{0};
  bool counter_known{false};
  CC1101RollingShutterCover *cover{nullptr};
#ifdef USE_SENSOR
  sensor::Sensor *counter_sensor{nullptr};
  sensor::Sensor *rssi_sensor{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  /// Carries the shutter's own id. Constant, so published once at startup.
  text_sensor::TextSensor *id_sensor{nullptr};
#endif
};

/// Drives one CC1101 module: transmits commands and decodes what it hears.
class CC1101RollingShutter : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  // -- configuration, set from the YAML schema --------------------------
  void set_gdo0_pin(uint8_t pin) { this->gdo0_pin_ = pin; }
  void set_spi_pins(uint8_t sck, uint8_t miso, uint8_t mosi, uint8_t cs) {
    this->sck_pin_ = sck;
    this->miso_pin_ = miso;
    this->mosi_pin_ = mosi;
    this->cs_pin_ = cs;
    this->custom_spi_pins_ = true;
  }
  void set_frequency(float mhz) { this->frequency_ = mhz; }
  void set_deviation(float khz) { this->deviation_ = khz; }
  void set_data_rate(float kbaud) { this->data_rate_ = kbaud; }
  void set_rx_bandwidth(float khz) { this->rx_bandwidth_ = khz; }
  void set_sync_word(uint8_t high, uint8_t low) {
    this->sync_high_ = high;
    this->sync_low_ = low;
  }
  void set_output_power(int8_t dbm) { this->output_power_ = dbm; }
  void set_repeats(uint8_t repeats) { this->repeats_ = repeats; }
  void set_frames_per_press(uint8_t frames) { this->frames_per_press_ = frames; }
  void set_burst_window(uint32_t ms) { this->burst_window_ = ms; }
  void set_rssi_threshold(int8_t dbm) { this->rssi_threshold_ = dbm; }

  // -- wiring, called from generated code -------------------------------
  void register_cover(uint32_t key, CC1101RollingShutterCover *cover);
#ifdef USE_SENSOR
  void set_counter_sensor(uint32_t key, sensor::Sensor *sensor);
  void set_rssi_sensor(uint32_t key, sensor::Sensor *sensor);
#endif
#ifdef USE_TEXT_SENSOR
  void set_discovered_sensor(text_sensor::TextSensor *sensor) {
    this->discovered_sensor_ = sensor;
  }
  void set_id_sensor(uint32_t key, text_sensor::TextSensor *sensor);
#endif
#ifdef USE_BINARY_SENSOR
  void set_spi_sensor(binary_sensor::BinarySensor *sensor) {
    this->spi_sensor_ = sensor;
  }
#endif

  /// Transmit a command, continuing this shutter's counter sequence.
  void send(uint32_t key, uint8_t command);

  /// Whether the CC1101 is answering on SPI.
  bool radio_ok() const { return this->radio_ok_; }

 protected:
#ifdef USE_ARDUINO
  /// Reset the module, check it answers, and write the whole configuration.
  bool bring_up_radio_();
#endif
  void set_radio_ok_(bool ok);
  ShutterSlot *slot_for_(uint32_t key);
  void handle_frame_(const uint8_t *frame, int len, int rssi);
  void report_heard_(uint32_t key, bool configured);
  void publish_counter_(ShutterSlot *slot);

  uint8_t gdo0_pin_{5};
  // Only meaningful when custom_spi_pins_ is set; otherwise the driver's own
  // per-platform defaults apply (ESP8266: 14, 12, 13, 15).
  uint8_t sck_pin_{0};
  uint8_t miso_pin_{0};
  uint8_t mosi_pin_{0};
  uint8_t cs_pin_{0};
  bool custom_spi_pins_{false};
  float frequency_{867.944f};
  float deviation_{55.0f};
  float data_rate_{9.57f};
  float rx_bandwidth_{162.5f};
  uint8_t sync_high_{0x4b};
  uint8_t sync_low_{0xd4};
  int8_t output_power_{12};
  uint8_t repeats_{4};
  uint8_t frames_per_press_{4};
  uint32_t burst_window_{1500};
  int8_t rssi_threshold_{-95};

  std::vector<ShutterSlot> slots_;
  /// De-duplication of the 4-16 frames one press produces, per shutter.
  std::vector<uint32_t> last_press_keys_;
  std::vector<uint32_t> last_press_times_;
  std::vector<uint8_t> last_press_commands_;
  uint32_t last_unknown_key_{0};
  bool has_unknown_{false};

  /// Where ReceiveData() puts what it read. See RX_BUFFER_LEN for why it is
  /// this big, and why it is not on the stack.
  uint8_t rx_buffer_[RX_BUFFER_LEN];

  bool radio_ok_{false};
  bool radio_state_known_{false};
  uint32_t last_probe_{0};

#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *discovered_sensor_{nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *spi_sensor_{nullptr};
#endif
};

/// Format a 4-byte identifier as the 8 hex digits used everywhere else.
std::string key_to_string(uint32_t key);

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
