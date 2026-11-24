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
