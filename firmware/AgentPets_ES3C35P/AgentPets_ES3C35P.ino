#include <Arduino.h>
#include <cJSON.h>
#include <driver/gpio.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>
#include "habitat.h"
#include "bluetooth_link.h"
#include "button_audio.h"

static char record[4096];
static size_t recordSize = 0;
static bool discarding = false;

void setup()
{
  gpio_deep_sleep_hold_dis(); gpio_hold_dis(GPIO_NUM_41); gpio_hold_dis(GPIO_NUM_1);
  rtc_gpio_deinit(GPIO_NUM_0);
  setCpuFrequencyMhz(160);
  Serial.setRxBufferSize(8192);
  Serial.begin(115200);
  habitatBegin();
  bluetoothBegin();
  Serial.printf("{\"event\":\"ready\",\"firmware\":\"agent-pets-native\",\"version\":1,\"wake_cause\":%d}\n",int(esp_sleep_get_wakeup_cause()));
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
        else if (strcmp(habitatString(root, "type"), "power_menu") == 0) {
          const cJSON* show=cJSON_GetObjectItemCaseSensitive(root,"show");
          habitatPowerMenu(!cJSON_IsFalse(show));
          Serial.println("{\"event\":\"power_menu\"}");
        }
        else if (strcmp(habitatString(root, "type"), "battery_status") == 0) habitatBatteryReport();
        else if (strcmp(habitatString(root, "type"), "power_status") == 0) habitatPowerReport();
        else if (strcmp(habitatString(root, "type"), "power_test") == 0) {
          const cJSON* timeout=cJSON_GetObjectItemCaseSensitive(root,"idle_ms");
          const cJSON* warning=cJSON_GetObjectItemCaseSensitive(root,"warning_ms");
          if (cJSON_IsNumber(timeout) && cJSON_IsNumber(warning) && timeout->valuedouble>=0 && timeout->valuedouble<=1800000 && warning->valuedouble>=0 && warning->valuedouble<=10000)
            habitatPowerTest(timeout->valueint,warning->valueint);
          habitatPowerReport();
        }
        else if (strcmp(habitatString(root, "type"), "wake") == 0) { habitatInteraction(); habitatPowerReport(); }
        else if (strcmp(habitatString(root, "type"), "settings") == 0) {
          const cJSON* page = cJSON_GetObjectItemCaseSensitive(root, "page");
          const cJSON* battery = cJSON_GetObjectItemCaseSensitive(root, "battery_installed");
          if (cJSON_IsBool(battery)) habitatBatteryInstalled(cJSON_IsTrue(battery));
          const cJSON* brightness = cJSON_GetObjectItemCaseSensitive(root, "brightness");
          if (cJSON_IsNumber(brightness) && brightness->valuedouble == brightness->valueint &&
              brightness->valueint >= 1 && brightness->valueint <= 100)
            habitatSetBrightness(brightness->valueint);
          habitatSettings(cJSON_IsNumber(page) ? page->valueint : 1);
          Serial.printf("{\"event\":\"display_settings\",\"brightness\":%u}\n", habitatBrightness());
          const cJSON* deep=cJSON_GetObjectItemCaseSensitive(root,"deep_sleep");
          if (cJSON_IsTrue(deep) && cJSON_IsNumber(page) && page->valueint==3) {
            const cJSON* timer=cJSON_GetObjectItemCaseSensitive(root,"test_wake_seconds");
            habitatDeepSleep(cJSON_IsNumber(timer)?constrain(timer->valueint,0,60):0);
          }
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
  delay(habitatScreenOff() ? 20 : 5);
}
