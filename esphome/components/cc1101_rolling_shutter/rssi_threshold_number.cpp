#include "rssi_threshold_number.h"

#include "esphome/core/log.h"

namespace esphome {
namespace cc1101_rolling_shutter {

static const char *const TAG = "cc1101_rolling_shutter.number";

void RssiThresholdNumber::setup() {
  // Starts from whatever the YAML says, then a stored value wins if there is
  // one — a threshold found by trial is worth more than the one guessed when
  // the configuration was written.
  float value = this->parent_ != nullptr ? this->parent_->rssi_threshold() : 0.0f;

  if (this->restore_) {
    this->pref_ = this->make_entity_preference<float>();
    float restored;
    if (this->pref_.load(&restored))
      value = restored;
  }

  this->apply_(value);
}

void RssiThresholdNumber::dump_config() { LOG_NUMBER("", "CC1101 RSSI threshold", this); }

void RssiThresholdNumber::control(float value) {
  this->apply_(value);
  if (this->restore_)
    this->pref_.save(&value);
}

void RssiThresholdNumber::apply_(float value) {
  if (this->parent_ != nullptr)
    this->parent_->set_rssi_threshold((int8_t) value);
  this->publish_state(value);
  ESP_LOGD(TAG, "Ignoring frames below %.0f dBm", value);
}

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
