#pragma once
#include <stdint.h>
// Approximate loaded single-cell LiPo curve; not a fuel gauge.
constexpr uint8_t batteryLevel(uint16_t mv) {
  constexpr uint16_t voltage[] = {3200,3500,3600,3700,3800,3900,4000,4100,4200};
  constexpr uint8_t level[] = {0,5,10,25,50,70,85,95,100};
  if (mv<=voltage[0]) return 0;
  for (int i=1;i<9;++i) if(mv<voltage[i]) {
    int percent=level[i-1]+uint32_t(mv-voltage[i-1])*(level[i]-level[i-1])/(voltage[i]-voltage[i-1]);
    return ((percent+2)/5)*5;
  }
  return 100;
}
static_assert(batteryLevel(2500)==0 && batteryLevel(3200)==0 && batteryLevel(3800)==50 && batteryLevel(4200)==100 && batteryLevel(4400)==100,
              "Battery curve must be bounded and preserve its reference points");
