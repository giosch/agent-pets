#pragma once
#include <stdint.h>

// Pure timing policy: no heartbeat, clock, or elapsed-display updates enter here.
struct PowerPolicy {
  enum class Stage { Eco, Dimming, Off };
  Stage stage = Stage::Eco;
  uint32_t last = 0, timeout = 300000, warning = 10000;
  constexpr bool interact(uint32_t now) {
    bool consumed = stage != Stage::Eco;
    stage = Stage::Eco; last = now; return consumed;
  }
  constexpr Stage tick(uint32_t now) {
    uint32_t age = now - last;
    stage = !timeout || age < timeout ? Stage::Eco
          : age - timeout < warning ? Stage::Dimming : Stage::Off;
    return stage;
  }
  constexpr uint8_t level(uint8_t normal, uint32_t now) const {
    if (stage == Stage::Off) return 0;
    if (stage == Stage::Eco) return normal;
    uint32_t age = now - last - timeout;
    uint8_t target = normal >= 10 ? normal / 10 : 1;
    return age >= 1500 ? target : normal - (uint32_t(normal - target) * age / 1500);
  }
};

constexpr bool powerPolicyChecks() {
  PowerPolicy p; p.timeout=1000; p.warning=100;
  if (p.tick(999)!=PowerPolicy::Stage::Eco || p.interact(999)) return false;
  if (p.tick(1999)!=PowerPolicy::Stage::Dimming || !p.interact(2000)) return false;
  if (p.tick(3100)!=PowerPolicy::Stage::Off || !p.interact(3101)) return false;
  p.timeout=0; if(p.tick(0xffffffff)!=PowerPolicy::Stage::Eco) return false;
  p.timeout=100; p.last=0xfffffff0; if(p.tick(90)!=PowerPolicy::Stage::Dimming) return false;
  p.last=0; p.stage=PowerPolicy::Stage::Off; if(p.level(200,0)!=0) return false;
  p.stage=PowerPolicy::Stage::Dimming; p.timeout=1000;
  return p.level(200,1000)==200 && p.level(200,2500)==20;
}
static_assert(powerPolicyChecks(), "Idle boundaries, wake consumption, disabled timeout and timer wrap must hold");
