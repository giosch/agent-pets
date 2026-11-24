#pragma once
#include <cJSON.h>
void habitatBegin();
void habitatTick();
bool habitatReceive(const cJSON* root, bool bluetooth = false);
void habitatSettings(int page);
void habitatCapture();
void habitatAudioTest();
const char* habitatString(const cJSON* object, const char* field);

bool habitatInspect(int index);

bool habitatConnectionInfo();

uint8_t habitatBrightness();
void habitatSetBrightness(int percent, bool save = true);

void habitatInteraction();
bool habitatScreenOff();
void habitatPowerReport();
void habitatPowerTest(uint32_t timeout, uint32_t warning);
bool habitatDeepSleep(uint32_t testWakeSeconds = 0);

void habitatBatteryInstalled(bool installed);
void habitatBatteryReport();

void habitatPowerMenu(bool visible = true);
