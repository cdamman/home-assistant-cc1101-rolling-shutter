#pragma once

#include "esphome/components/cover/cover.h"
#include "esphome/core/component.h"

#include "cc1101_rolling_shutter.h"

namespace esphome {
namespace cc1101_rolling_shutter {

/// One shutter, as a cover.
///
/// The motors report nothing, so the position is inferred — from the commands
/// we send and, equally, from the ones the original remotes send, which the
/// hub decodes off the air. There is no intermediate position: a setpoint is
/// snapped to fully open or fully closed.
class CC1101RollingShutterCover : public cover::Cover, public Component {
 public:
  void setup() override;
  void dump_config() override;
  cover::CoverTraits get_traits() override;

  void set_parent(CC1101RollingShutter *parent) { this->parent_ = parent; }
  void set_shutter_key(uint32_t key) { this->key_ = key; }

  /// A frame for this shutter was heard on the air.
  void on_air_command(uint8_t command);

 protected:
  void control(const cover::CoverCall &call) override;
  void publish_position_(float position);

  CC1101RollingShutter *parent_{nullptr};
  uint32_t key_{0};
};

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
