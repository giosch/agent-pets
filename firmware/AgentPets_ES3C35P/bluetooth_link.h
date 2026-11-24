#pragma once
#include <stdint.h>
void bluetoothBegin();
void bluetoothTick();
void bluetoothPair();
void bluetoothCancelPair();
void bluetoothForget();
bool bluetoothConnected();
bool bluetoothBonded();
unsigned bluetoothPairSeconds();
const char* bluetoothName();
const char* bluetoothTransport();
uint32_t bluetoothGeneration();
