#include "shutter_cover.h"

#include "esphome/core/log.h"

namespace esphome {
namespace cc1101_rolling_shutter {

static const char *const TAG = "cc1101_rolling_shutter.cover";

void CC1101RollingShutterCover::setup() {
  // apply() only restores the fields and publishes; it does not run control(),
  // so a reboot never puts a command on the air.
  auto restore = this->restore_state_();
  if (restore.has_value()) {
    restore->apply(this);
    ESP_LOGD(TAG, "Shutter %s restored as %s", key_to_string(this->key_).c_str(),
             this->position == cover::COVER_CLOSED ? "closed" : "open");
    return;
  }
  // Nothing stored — the first boot, or the entity was renamed, which moves
  // the key its state is filed under. Start from a concrete state rather than
  // unknown, so that a voice assistant querying the shutter does not see it as
  // offline. Flip to COVER_CLOSED to start closed instead.
  //
  // Not saved: it is a guess, and storing it would make the next boot look
  // like a restore.
  this->position = cover::COVER_OPEN;
  this->publish_state(false);
}

void CC1101RollingShutterCover::dump_config() {
  LOG_COVER("", "CC1101 Shutter", this);
  ESP_LOGCONFIG(TAG, "  Shutter ID: %s", key_to_string(this->key_).c_str());
}

cover::CoverTraits CC1101RollingShutterCover::get_traits() {
  auto traits = cover::CoverTraits();
  traits.set_supports_stop(true);
  // A position is published even though the hardware has none: it is what
  // keeps "stop" available at all times in assistants that derive it from
  // whether the cover reports as movable, and it carries open/closed through.
  traits.set_supports_position(true);
  traits.set_is_assumed_state(false);
  return traits;
}

void CC1101RollingShutterCover::publish_position_(float position) {
  this->position = position;
  // Saved, so the position survives a reboot or an OTA update. On the ESP8266
  // that lands in RTC memory unless the node sets `restore_from_flash: true`,
  // which is what carries it across a power cut as well.
  this->publish_state();
}

void CC1101RollingShutterCover::control(const cover::CoverCall &call) {
  if (this->parent_ == nullptr)
    return;

  if (call.get_stop()) {
    // Where it stopped is unknowable, so the cached position is left alone.
    this->parent_->send(this->key_, CMD_STOP);
    return;
  }

  if (!call.get_position().has_value())
    return;

  const float requested = *call.get_position();
  const bool opening = requested >= 0.5f;
  const float target = opening ? cover::COVER_OPEN : cover::COVER_CLOSED;

  // Publish before transmitting: the burst takes about half a second, and an
  // assistant that reads the state straight after issuing the command would
  // otherwise see the old one and flicker.
  this->publish_position_(target);
  ESP_LOGD(TAG, "Shutter %s: %s", key_to_string(this->key_).c_str(),
           opening ? "open" : "close");
  this->parent_->send(this->key_, opening ? CMD_UP : CMD_DOWN);
}

void CC1101RollingShutterCover::on_air_command(uint8_t command) {
  switch (command) {
    case CMD_UP:
      this->publish_position_(cover::COVER_OPEN);
      break;
    case CMD_DOWN:
      this->publish_position_(cover::COVER_CLOSED);
      break;
    default:
      // Stop says nothing about where it ended up; keep the last known state.
      break;
  }
}

}  // namespace cc1101_rolling_shutter
}  // namespace esphome
