#pragma once

#include "esphome/components/number/number.h"
#include "esphome/core/component.h"
#include "esphome/core/preferences.h"

#include "cc1101_rolling_shutter.h"

namespace esphome {
namespace cc1101_rolling_shutter {

/// The noise floor, as a number you can move from Home Assistant.
///
/// Worth having as an entity rather than only a YAML value: whether a frame is
/// noise or a remote two rooms away is a question about your walls, and the
/// answer is found by turning the knob and pressing a button — not by editing,
/// recompiling and re-flashing between each attempt.
class RssiThresholdNumber : public number::Number, public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_CONNECTION; }

  void set_parent(CC1101RollingShutter *parent) { this->parent_ = parent; }
  void set_restore(bool restore) { this->restore_ = restore; }

 protected:
  void control(float value) override;
  void apply_(float value);

  CC1101RollingShutter *parent_{nullptr};
  bool restore_{true};
  ESPPreferenceObject pref_;
};

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
