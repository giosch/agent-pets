#include <Arduino.h>
#include <cJSON.h>
#include "habitat.h"
#include "bluetooth_link.h"
#include "button_audio.h"

static char record[4096];
static size_t recordSize = 0;
static bool discarding = false;

void setup()
{
  Serial.setRxBufferSize(8192);
  Serial.begin(115200);
  habitatBegin();
  bluetoothBegin();
  Serial.println("{\"event\":\"ready\",\"firmware\":\"agent-pets-native\",\"version\":1}");
}

void loop()
{
  for (int budget = 0; budget < 4096 && Serial.available(); ++budget) {
    char c = Serial.read();
    if (c == '\n') {
      if (!discarding && recordSize > 0) {
        record[recordSize] = '\0';
        cJSON* root = cJSON_Parse(record);
        if (strcmp(habitatString(root, "type"), "capture") == 0) habitatCapture();
        else if (strcmp(habitatString(root, "type"), "preview_mute") == 0) {
          const cJSON* enabled = cJSON_GetObjectItemCaseSensitive(root, "enabled");
          if (cJSON_IsBool(enabled)) buttonAudioPreviewMute(cJSON_IsTrue(enabled));
          Serial.println("{\"event\":\"preview_mute\"}");
        }
        else if (strcmp(habitatString(root, "type"), "connection_info") == 0) {
          Serial.println(habitatConnectionInfo() ? "{\"event\":\"connection_info\"}" : "{\"event\":\"settings_open\"}");
        }
        else if (strcmp(habitatString(root, "type"), "pet_info") == 0) {
          const cJSON* index = cJSON_GetObjectItemCaseSensitive(root, "index");
          Serial.println(cJSON_IsNumber(index) && habitatInspect(index->valueint) ? "{\"event\":\"pet_info\"}" : "{\"event\":\"pet_not_found\"}");
        }
        else if (strcmp(habitatString(root, "type"), "audio_test") == 0) habitatAudioTest();
        else if (strcmp(habitatString(root, "type"), "ble_pair") == 0) { bluetoothPair(); habitatSettings(2); }
        else if (strcmp(habitatString(root, "type"), "settings") == 0) {
          const cJSON* page = cJSON_GetObjectItemCaseSensitive(root, "page");
          habitatSettings(cJSON_IsNumber(page) ? constrain(page->valueint, 0, 2) : 1);
        }
        else Serial.println(habitatReceive(root) ? "{\"event\":\"snapshot_applied\"}" : "{\"event\":\"invalid_snapshot\"}");
        cJSON_Delete(root);
      }
      recordSize = 0;
      discarding = false;
    } else if (!discarding && c != '\r') {
      if (recordSize < sizeof(record) - 1) record[recordSize++] = c;
      else {
        discarding = true;
        Serial.println("{\"event\":\"record_too_large\"}");
      }
    }
  }
  bluetoothTick();
  habitatTick();
  delay(1);
}
