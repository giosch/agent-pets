#pragma once
#include <stdint.h>
struct BootGesture {
  enum Event { None, Pressed, ShortPress, LongPress };
  bool raw=false, down=false, sent=false;
  uint32_t changed=0, pressed=0;
  constexpr Event update(bool input, uint32_t now) {
    if(input!=raw) { raw=input; changed=now; }
    if(input!=down && now-changed>=35) {
      down=input;
      if(input) { pressed=now; sent=false; return Pressed; }
      return sent?None:ShortPress;
    }
    if(down && !sent && now-pressed>=1200) { sent=true; return LongPress; }
    return None;
  }
};
constexpr bool bootGestureChecks() {
  BootGesture a;
  if(a.update(true,0)!=BootGesture::None || a.update(true,34)!=BootGesture::None || a.update(true,35)!=BootGesture::Pressed) return false;
  if(a.update(false,100)!=BootGesture::None || a.update(false,135)!=BootGesture::ShortPress) return false;
  BootGesture b; b.update(true,0); b.update(true,35);
  if(b.update(true,1234)!=BootGesture::None || b.update(true,1235)!=BootGesture::LongPress || b.update(true,3000)!=BootGesture::None) return false;
  b.update(false,4000);
  return b.update(false,4035)==BootGesture::None;
}
static_assert(bootGestureChecks(), "Debounce, short press, long press and release must be distinct");
