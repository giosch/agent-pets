#include <Arduino.h>
#include <Preferences.h>
#include <math.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>
#include <driver/gpio.h>
#include "power_policy.h"
#include "battery_level.h"
#include "boot_gesture.h"
#include "LGFX_ES3C35P.hpp"
#include "habitat.h"
#include "device_art.h"
#include "button_audio.h"
#include "bluetooth_link.h"

static LGFX lcd;
static LGFX_Sprite canvas(&lcd), backdrop(&lcd), panelCanvas(&lcd);
static Preferences preferences;
static bool batteryInstalled = false;
static uint16_t batteryMv = 0;
static uint32_t lastBatteryRead = 0;
static bool powerMenu = false;

static void readBattery(bool force = false)
{
  if (!force && (!batteryInstalled || (lastBatteryRead && millis()-lastBatteryRead<15000))) return;
  static bool configured = false;
  if (!configured) { analogSetPinAttenuation(8,ADC_11db); configured=true; }
  uint32_t total=0;
  for(int i=0;i<24;++i) total+=analogReadMilliVolts(8);
  batteryMv=(total*2+12)/24;
  lastBatteryRead=millis();
}

void habitatBatteryInstalled(bool installed)
{
  batteryInstalled=installed;
  preferences.putBool("battery",installed);
  if(installed) readBattery(true);
}

void habitatBatteryReport()
{
  readBattery(true);
  Serial.printf("{\"event\":\"battery\",\"installed\":%s,\"mv\":%u,\"percent\":%d}\n",
    batteryInstalled?"true":"false",batteryMv,batteryInstalled?int(batteryLevel(batteryMv)):-1);
}

static uint8_t character = 0, scenery = 1;
static uint8_t brightness = 200;
static PowerPolicy powerPolicy;
static uint8_t idleMinutes = 5;
static bool wakeTouchGuard = false, redrawRequested = true;
static String pcActivityToken;
static uint32_t deepConfirmUntil = 0, receivedSnapshots = 0, renderedFrames = 0;
static void render();
static void applyPowerBrightness()
{
  uint8_t output = powerPolicy.level(brightness, millis());
  if (lcd.getBrightness() != output) lcd.setBrightness(output);
}

void habitatInteraction()
{
  bool wake = powerPolicy.interact(millis());
  if (wake) {
    wakeTouchGuard = true;
    buttonAudioSleep(false);
    redrawRequested = true;
  }
  if (!wake) applyPowerBrightness();
}

bool habitatScreenOff() { return powerPolicy.stage == PowerPolicy::Stage::Off; }

static bool demo = false, connected = false;
static bool bluetoothSource = false;
static uint32_t lastSnapshot = 0, lastBridge = 0, bridgeGeneration = 0;
static bool bridgeSeen = false, backendOnline = false, snapshotCurrent = false;
static constexpr uint32_t BRIDGE_TIMEOUT_MS = 3500;
enum class LinkState { PcOffline, CompanionOffline, BackendOffline, Live };

static bool bridgeActive()
{
  return bridgeSeen && millis() - lastBridge < BRIDGE_TIMEOUT_MS &&
         (!bluetoothSource || bridgeGeneration == bluetoothGeneration());
}

static LinkState linkState()
{
  bool active = bridgeActive();
  if (!bluetoothConnected() && !(active && !bluetoothSource)) return LinkState::PcOffline;
  if (!active) return LinkState::CompanionOffline;
  if (!backendOnline || !snapshotCurrent || millis() - lastSnapshot >= 5000) return LinkState::BackendOffline;
  return LinkState::Live;
}

static const char* linkLabel()
{
  switch (linkState()) {
    case LinkState::PcOffline: return "PC disconnected";
    case LinkState::CompanionOffline: return "Companion offline";
    case LinkState::BackendOffline: return "Backend not found";
    default: return bluetoothSource ? bluetoothTransport() : "USB";
  }
}

static void bridgeReceived(bool wireless, bool online)
{
  if (!online || !bridgeSeen || wireless != bluetoothSource ||
      (wireless && bridgeGeneration != bluetoothGeneration())) snapshotCurrent = false;
  bridgeSeen = true;
  lastBridge = millis();
  bridgeGeneration = bluetoothGeneration();
  bluetoothSource = wireless;
  backendOnline = online;
  if (!online) connected = false;
}
static bool clockKnown = false;
static uint32_t clockSeconds = 0, clockUpdated = 0;
static int totalPets = 0;
static int pressedControl = -1;
static uint32_t pressedUntil = 0;
static int settingsPage = 0; // 0 habitat, 1 audio, 2 Bluetooth, 3 display, 4 battery
void habitatPowerReport()
{
  const char* stage = habitatScreenOff() ? "off" : powerPolicy.stage == PowerPolicy::Stage::Dimming ? "dimming" : "eco";
  Serial.printf("{\"event\":\"power\",\"state\":\"%s\",\"brightness\":%u,\"output\":%u,\"idle_ms\":%u,\"timeout_ms\":%u,\"warning_ms\":%u,\"cpu_mhz\":%u,\"audio_parked\":%s,\"settings\":%d,\"snapshots\":%u,\"frames\":%u,\"wake_cause\":%d}\n",
    stage,habitatBrightness(),powerPolicy.level(brightness,millis()),millis()-powerPolicy.last,
    powerPolicy.timeout,powerPolicy.warning,getCpuFrequencyMhz(),buttonAudioSleeping()?"true":"false",settingsPage,receivedSnapshots,renderedFrames,int(esp_sleep_get_wakeup_cause()));
}

static uint32_t forgetUntil = 0;
static bool adjustingVolume = false, adjustingBrightness = false;
static bool uiVisible = false;
static uint32_t lastUiTouch = 0;
static constexpr uint32_t UI_IDLE_MS = 8000;
static constexpr int PET_TOP = 132; // Ground the pets 30 px lower in the scenery.

static constexpr uint16_t uiColor(uint32_t rgb)
{
  return ((rgb >> 19) << 11) | (((rgb >> 10) & 63) << 5) | ((rgb >> 3) & 31);
}

static constexpr uint16_t UI_INK = uiColor(0x24443B);
static constexpr uint16_t UI_PAPER = uiColor(0xF5F3E8);
static constexpr uint16_t UI_SURFACE = uiColor(0xFFFDF5);
static constexpr uint16_t UI_LINE = uiColor(0xCAD5C4);
static constexpr uint16_t UI_ACCENT = uiColor(0x356A53);
static constexpr uint16_t UI_PRESSED = uiColor(0xDFEAD6);
static constexpr uint16_t UI_SHADOW = uiColor(0xB3BFAF);
static constexpr uint16_t UI_SECONDARY = uiColor(0x648074);

static void drawBattery()
{
  if (!batteryInstalled || batteryMv<2500 || batteryMv>4400) return;
  int x=uiVisible?296:414, y=uiVisible?12:10;
  if(uiVisible) canvas.fillRoundRect(x,y,78,28,9,UI_SURFACE);
  else x-=4;
  uint8_t percent=batteryLevel(batteryMv);
  uint16_t ink=uiVisible?(percent<=15?uiColor(0xAD674B):UI_INK):UI_SECONDARY;
  int bx=x+8, by=y+9;
  canvas.drawRoundRect(bx,by,19,10,2,ink);
  canvas.fillRect(bx+19,by+3,2,4,ink);
  if(percent) canvas.fillRect(bx+2,by+2,max(1,int(percent)*15/100),6,ink);
  canvas.setFont(&fonts::Font0);canvas.setTextSize(1);canvas.setTextDatum(top_left);canvas.setTextColor(ink);
  canvas.drawString("~"+String(percent)+"%",x+34,y+10);
}

struct Pet {
  String id, activity, attention, moment, phase, lastPose, title, source, progressKind;
  uint32_t order = 0, since = 0, arrived = 0, momentUntil = 0, poseSince = 0;
  uint32_t lastFailure = 0, travelStart = 0, travelUntil = 0;
  double token = -1;
  int helpers = 0, calls = 0, completions = 0, failures = 0;
  int32_t elapsed = -1, progressDone = -1, progressTotal = 0;
  uint32_t elapsedUpdated = 0;
  int fromX = 0, targetX = 0;
};

struct Departure {
  Pet pet;
  uint32_t started = 0;
  bool closed = false;
};

static Pet pets[3], demoPets[3], resting;
static Departure departures[3];
static int petCount = 0;
static String bubblePet;
static uint32_t bubbleUntil = 0, lastAutoBubble = 0;
static bool bubbleAutomatic = false;
static constexpr uint32_t PET_INFO_MS = 8000, ALERT_BUBBLE_MS = 4000, ALERT_COOLDOWN_MS = 30000;

static void showBubble(const Pet& pet, bool automatic)
{
  bubblePet = pet.id;
  bubbleAutomatic = automatic;
  bubbleUntil = millis() + (automatic ? ALERT_BUBBLE_MS : PET_INFO_MS);
  if (automatic) lastAutoBubble = millis();
  PetVoice phrase = pet.attention == "approval" ? PetVoice::Approval
      : pet.attention == "question" ? PetVoice::Question
      : pet.attention == "failure" ? PetVoice::Failure
      : pet.attention == "ready" || pet.activity == "idle" ? PetVoice::Ready : PetVoice::Working;
  if (connected || demo) buttonAudioSpeak(phrase);
}

const char* habitatString(const cJSON* object, const char* field)
{
  const cJSON* value = cJSON_GetObjectItemCaseSensitive(object, field);
  return cJSON_IsString(value) ? value->valuestring : "";
}

static bool integer(const cJSON* value)
{
  return cJSON_IsNumber(value) && value->valuedouble >= 0 &&
         value->valuedouble <= 2147483647 && value->valuedouble == value->valueint;
}

static bool blocking(const String& attention)
{
  return attention == "question" || attention == "approval" || attention == "failure";
}

static int slotX(int slot, int count)
{
  int gap = (432 - count * 128) / (count + 1);
  return 24 + gap + slot * (128 + gap);
}

bool habitatReceive(const cJSON* root, bool wireless)
{
  if (!strcmp(habitatString(root, "type"), "bridge_status")) {
    const cJSON* version = cJSON_GetObjectItemCaseSensitive(root, "version");
    const cJSON* backend = cJSON_GetObjectItemCaseSensitive(root, "backend");
    if (!cJSON_IsNumber(version) || version->valuedouble != 1 || !cJSON_IsBool(backend)) return false;
    bridgeReceived(wireless, cJSON_IsTrue(backend));
    return true;
  }
  const cJSON* sessions = cJSON_GetObjectItemCaseSensitive(root, "sessions");
  const cJSON* version = cJSON_GetObjectItemCaseSensitive(root, "version");
  const cJSON* total = cJSON_GetObjectItemCaseSensitive(root, "total");
  int count = cJSON_GetArraySize(sessions);
  if (!cJSON_IsNumber(version) || version->valuedouble != 1 ||
      strcmp(habitatString(root, "type"), "snapshot") || !cJSON_IsArray(sessions) ||
      count > 3 || !integer(total) || total->valueint < count) return false;
  const cJSON* localTime = cJSON_GetObjectItemCaseSensitive(root, "local_time");
  if (localTime && (!integer(localTime) || localTime->valueint >= 86400)) return false;
  const cJSON* activity = cJSON_GetObjectItemCaseSensitive(root, "activity_token");
  if (activity && (!cJSON_IsString(activity) || strlen(activity->valuestring) > 64)) return false;
  bool changed = count != petCount || total->valueint != totalPets;
  Pet next[3];
  uint32_t now = millis();
  bool mayAnnounce = connected && snapshotCurrent && !demo && !settingsPage &&
      (!bubbleUntil || int32_t(bubbleUntil - now) <= 0) &&
      (!lastAutoBubble || now - lastAutoBubble >= ALERT_COOLDOWN_MS);
  int announce = -1;
  for (int i = 0; i < count; ++i) {
    const cJSON* item = cJSON_GetArrayItem(sessions, i);
    const cJSON* order = cJSON_GetObjectItemCaseSensitive(item, "order");
    const cJSON* helpers = cJSON_GetObjectItemCaseSensitive(item, "helpers");
    const cJSON* calls = cJSON_GetObjectItemCaseSensitive(item, "active_calls");
    const cJSON* elapsed = cJSON_GetObjectItemCaseSensitive(item, "elapsed");
    const cJSON* progressDone = cJSON_GetObjectItemCaseSensitive(item, "progress_done");
    const cJSON* progressTotal = cJSON_GetObjectItemCaseSensitive(item, "progress_total");
    String progressKind = habitatString(item, "progress_kind");
    if (elapsed && !integer(elapsed)) return false;
    if ((progressDone || progressTotal) && (!integer(progressDone) || !integer(progressTotal) ||
        progressDone->valueint > progressTotal->valueint ||
        (progressKind != "steps" && progressKind != "tasks"))) return false;
    String id = habitatString(item, "id");
    if (!id.length() || !strlen(habitatString(item, "activity")) ||
        !strlen(habitatString(item, "attention")) || !integer(order) || !integer(helpers) ||
        (calls && !integer(calls))) return false;
    for (int j = 0; j < i; ++j) if (next[j].id == id) return false;
    bool found = false;
    for (int j = 0; j < petCount; ++j) {
      if (pets[j].id == id) { next[i] = pets[j]; found = true; break; }
    }
    Pet& pet = next[i];
    String previousAttention = pet.attention;
    pet.id = id;
    pet.title = String(habitatString(item, "title")).substring(0, 384);
    pet.source = habitatString(item, "source");
    if (!pet.source.length()) pet.source = id.startsWith("claude:") ? "claude" : id.startsWith("codex:") ? "codex" : "";
    pet.activity = habitatString(item, "activity");
    pet.attention = habitatString(item, "attention");
    pet.order = order->valueint;
    if (!pet.title.length()) pet.title = String(pet.source == "claude" ? "Claude Code" : pet.source == "codex" ? "Codex" : "Pet") + " session " + String(pet.order + 1);
    if (mayAnnounce && announce < 0 && blocking(pet.attention) && pet.attention != previousAttention) announce = i;
    changed |= !found;
    if (found) for (int j = 0; j < petCount; ++j) if (pets[j].id == id)
      changed |= pets[j].activity != pet.activity || pets[j].attention != pet.attention ||
                 pets[j].title != pet.title || pets[j].helpers != helpers->valueint ||
                 pets[j].calls != (calls ? calls->valueint : 0) ||
                 pets[j].progressDone != (progressDone ? progressDone->valueint : -1);
    pet.helpers = helpers->valueint;
    pet.calls = calls ? calls->valueint : 0;
    pet.elapsed = elapsed ? elapsed->valueint : -1;
    pet.elapsedUpdated = now;
    pet.progressDone = progressDone ? progressDone->valueint : -1;
    pet.progressTotal = progressTotal ? progressTotal->valueint : 0;
    pet.progressKind = progressKind;
    String phase = pet.activity + "/" + pet.attention;
    if (phase != pet.phase) { pet.phase = phase; pet.since = now; }
    if (!found || pet.targetX != slotX(i, count)) {
      pet.fromX = found ? pet.targetX : slotX(i, count) - 48;
      pet.targetX = slotX(i, count);
      pet.travelStart = now;
      pet.travelUntil = now + (!found && petCount == 0 ? 1500 : 650);
    }
    if (!found) pet.arrived = now;
    const cJSON* token = cJSON_GetObjectItemCaseSensitive(item, "moment_token");
    String moment = habitatString(item, "moment");
    if (cJSON_IsNumber(token) && token->valuedouble != pet.token && moment.length()) {
      changed = true;
      pet.token = token->valuedouble;
      pet.moment = moment;
      pet.momentUntil = now + 1450;
      if (moment == "completed") ++pet.completions;
      if (moment == "setback") {
        pet.failures = now - pet.lastFailure < 30000 ? pet.failures + 1 : 1;
        pet.lastFailure = now;
      }
    }
    if (blocking(pet.attention) || (pet.moment == "completed" && pet.attention != "ready")) pet.moment = "";
    if (pet.attention != "none") pet.travelUntil = 0;
  }
  for (int j = 0; j < petCount; ++j) {
    bool retained = false;
    for (int i = 0; i < count; ++i) if (next[i].id == pets[j].id) retained = true;
    if (!retained) {
      departures[j].pet = pets[j];
      departures[j].started = now;
      departures[j].closed = total->valueint < totalPets;
    }
  }
  for (int i = 0; i < count; ++i) pets[i] = next[i];
  petCount = count;
  if (announce >= 0) showBubble(pets[announce], true);
  totalPets = total->valueint;
  connected = true;
  bridgeReceived(wireless, true);
  snapshotCurrent = true;
  lastSnapshot = now;
  ++receivedSnapshots;
  if (localTime) { clockKnown = true; clockSeconds = localTime->valueint; clockUpdated = now; }
  if (activity) {
    String token(activity->valuestring);
    if (token != pcActivityToken) { pcActivityToken = token; habitatInteraction(); }
  } else if (changed) habitatInteraction(); // Compatibility with older companions.
  return true;
}

static uint16_t hsl(float hue, float saturation, float lightness)
{
  float chroma = (1 - fabsf(2 * lightness - 1)) * saturation;
  float x = chroma * (1 - fabsf(fmodf(hue / 60, 2) - 1));
  float r = 0, g = 0, b = 0, m = lightness - chroma / 2;
  switch (int(hue / 60) % 6) {
    case 0: r = chroma; g = x; break;
    case 1: r = x; g = chroma; break;
    case 2: g = chroma; b = x; break;
    case 3: g = x; b = chroma; break;
    case 4: r = x; b = chroma; break;
    case 5: r = chroma; b = x; break;
  }
  return canvas.color565(roundf((r + m) * 255), roundf((g + m) * 255), roundf((b + m) * 255));
}

static void palette(uint32_t order, uint16_t colors[3])
{
  const DeviceCharacter& art = artCharacters[character];
  if (art.palettes) { memcpy(colors, art.colors[order % art.palettes], 6); return; }
  const int initial[] = {16, 168, 271, 43, 218, 326};
  float hue = order < 6 ? initial[order] : fmodf(order * 137.508, 360);
  colors[0] = hsl(hue, .67, .66);
  colors[1] = hsl(hue, .41, .43);
  colors[2] = hsl(hue, .80, .84);
}

static int drawRle(LGFX_Sprite& target, uint32_t offset, int width, int height,
                    int x, int y, int size, const uint16_t colors[3], int outputHeight = 0)
{
  int position = 0;
  int renderedHeight = outputHeight ? outputHeight : height * size / width;
  int firstVisibleY = y + renderedHeight;
  while (position < width * height) {
    uint16_t color = artData[offset] | uint16_t(artData[offset + 1]) << 8;
    offset += 2;
    int count = artData[offset++];
    bool visible = color != 0xF81F;
    if (colors && color >= 0xF81C && color <= 0xF81E) color = colors[0xF81E - color];
    while (count > 0) {
      int column = position % width, row = position / width;
      int run = min(count, width - column);
      if (visible) {
        int left = column * size / width, right = (column + run) * size / width;
        int top = row * renderedHeight / height, bottom = (row + 1) * renderedHeight / height;
        firstVisibleY = min(firstVisibleY, y + top);
        target.fillRect(x + left, y + top, right - left, bottom - top, color);
      }
      position += run;
      count -= run;
    }
  }
  return firstVisibleY;
}

static const DeviceAnimation& animation(const String& pose)
{
  for (const auto& art : artAnimations) if (art.character == character && pose == art.pose) return art;
  for (const auto& art : artAnimations)
    if (art.character == character && strcmp(art.pose, "idle") == 0) return art;
  return artAnimations[0];
}

static int drawPet(Pet& pet, const String& pose, int x, int y, int size, uint32_t elapsed)
{
  const DeviceAnimation& art = animation(pose);
  if (elapsed >= art.period && art.period > art.intro)
    elapsed = art.intro + (elapsed - art.intro) % (art.period - art.intro);
  int frame = min(uint32_t(art.count - 1), elapsed * art.count / max(uint32_t(1), art.period));
  uint16_t colors[3];
  palette(pet.order, colors);
  return drawRle(canvas, artFrames[art.first + frame], 128, 128, x, y, size, colors);
}

static String poseFor(Pet& pet, uint32_t now)
{
  if (!connected && !demo) return "offline";
  if (blocking(pet.attention)) return pet.attention;
  if (pet.moment.length() && int32_t(pet.momentUntil - now) > 0) {
    if (pet.moment == "completed" && pet.completions % 2 == 0) return "eureka";
    if (pet.moment == "setback" && pet.failures >= 2) return "overheated";
    return pet.moment == "forked" ? pet.activity : pet.moment;
  }
  if (pet.attention == "ready") return "ready";
  if (pet.travelUntil && int32_t(pet.travelUntil - now) > 0)
    return now - pet.arrived < 1500 ? "wake" : "walking";
  if (pet.calls > 1) return "parallel";
  uint32_t elapsed = now - pet.since;
  if (pet.activity == "idle" && elapsed >= 12000 && elapsed % 12000 < 3200) {
    const char* play[] = {"coffee", "groove", "hat"};
    return play[(elapsed / 12000 - 1 + pet.order) % 3];
  }
  if (pet.activity == "working" && elapsed >= 10000)
    return (elapsed / 10000) % 2 ? "thinking" : "pushing";
  return pet.activity;
}

static int petScreenX(const Pet& pet, uint32_t now)
{
  if (int32_t(pet.travelUntil - now) > 0) {
    float progress = min(1.0f, (now - pet.travelStart) / 650.0f);
    return pet.fromX + (pet.targetX - pet.fromX) * progress;
  }
  return pet.targetX;
}

static const char* petWords(const Pet& pet)
{
  if (!connected && !demo) return "I'm waiting for the connection.";
  if (pet.attention == "approval") return "I need your approval.";
  if (pet.attention == "question") return "I have a question for you.";
  if (pet.attention == "failure") return "Something needs your attention.";
  if (pet.attention == "ready") return "I'm ready when you are.";
  if (pet.calls > 1) return "I'm working on several things.";
  if (pet.activity == "editing") return "I'm editing files.";
  if (pet.activity == "inspecting") return "I'm looking through the details.";
  if (pet.activity == "executing") return "I'm running a command.";
  if (pet.activity == "building") return "I'm building the project.";
  if (pet.activity == "transferring") return "I'm moving files.";
  if (pet.activity == "researching") return "I'm researching.";
  if (pet.activity == "coordinating") return "I'm working with my helpers.";
  if (pet.activity == "external") return "I'm using a connected tool.";
  if (pet.activity == "idle") return "I'm taking a little break.";
  return "I'm working on it.";
}

static String fitBubbleText(String text, int width)
{
  text.replace("\n", " ");
  text.replace("\r", " ");
  if (canvas.textWidth(text) <= width) return text;
  while (text.length() && canvas.textWidth(text + "...") > width) {
    int cut = text.length() - 1;
    while (cut > 0 && (uint8_t(text[cut]) & 0xC0) == 0x80) --cut;
    text.remove(cut);
  }
  return text + "...";
}

struct BubbleLayout {
  String lines[3];
  int count = 0, titleHeight = 12, statusHeight = 10;
  float titleScale = .75f, statusScale = .625f;
  const lgfx::IFont* titleFont = &fonts::Font2;
};

static bool wrapBubbleLines(String text, int width, String lines[3], int& count)
{
  text.replace("\n", " "); text.replace("\r", " "); text.trim();
  count = 0;
  while (text.length() && count < 3) {
    if (canvas.textWidth(text) <= width) { lines[count++] = text; return true; }
    // Leave the last line intact so the fallback can mark truncation honestly.
    if (count == 2) { lines[count++] = text; return false; }
    int split = text.length();
    while (split > 0 && canvas.textWidth(text.substring(0, split)) > width) {
      --split;
      while (split > 0 && (uint8_t(text[split]) & 0xC0) == 0x80) --split;
    }
    if (!split) return false;
    int space = text.lastIndexOf(' ', split);
    if (space > 0) split = space;
    lines[count++] = text.substring(0, split);
    text = text.substring(split); text.trim();
  }
  return !text.length();
}

static BubbleLayout fitBubbleLayout(const String& title, const String& words, int width, int height)
{
  // Reserve 14 px side margins, 8 px vertical margins, a 10 px source label,
  // and 3 px gaps. Choose the largest title, then the largest status that fits.
  const int available = height - 16 - 10 - 6;
  BubbleLayout best;
  for (int goal = 32; goal >= 12; --goal) {
    BubbleLayout candidate;
    candidate.titleFont = goal >= 20 ? static_cast<const lgfx::IFont*>(&fonts::Font4) : &fonts::Font2;
    canvas.setFont(candidate.titleFont); canvas.setTextSize(1);
    candidate.titleScale = float(goal) / canvas.fontHeight();
    canvas.setTextSize(candidate.titleScale);
    candidate.titleHeight = canvas.fontHeight();
    bool complete = wrapBubbleLines(title, width, candidate.lines, candidate.count);
    if (complete && candidate.count == 2) {
      // Balance two title lines instead of leaving a lone short word below.
      int bestDifference = INT32_MAX;
      for (int split = title.indexOf(' '); split >= 0; split = title.indexOf(' ', split + 1)) {
        String first = title.substring(0, split), second = title.substring(split + 1);
        first.trim(); second.trim();
        int firstWidth = canvas.textWidth(first), secondWidth = canvas.textWidth(second);
        int difference = abs(firstWidth - secondWidth);
        if (first.length() && second.length() && firstWidth <= width && secondWidth <= width && difference < bestDifference) {
          candidate.lines[0] = first; candidate.lines[1] = second; bestDifference = difference;
        }
      }
    }
    int titleSpace = candidate.count * candidate.titleHeight + max(0, candidate.count - 1) * 2;
    if (!complete || !candidate.count) continue;
    for (int statusGoal = 20; statusGoal >= 14; --statusGoal) {
      canvas.setFont(&fonts::Font2); canvas.setTextSize(1);
      candidate.statusScale = float(statusGoal) / canvas.fontHeight();
      canvas.setTextSize(candidate.statusScale);
      candidate.statusHeight = canvas.fontHeight();
      if (titleSpace + candidate.statusHeight <= available && canvas.textWidth(words) <= width)
        return candidate;
    }
  }
  canvas.setFont(best.titleFont); canvas.setTextSize(best.titleScale);
  wrapBubbleLines(title, width, best.lines, best.count);
  if (best.count) best.lines[best.count - 1] = fitBubbleText(best.lines[best.count - 1], width);
  return best;
}

static String elapsedLabel(uint32_t seconds)
{
  if (seconds < 60) return String(seconds) + "s";
  if (seconds < 3600) return String(seconds / 60) + "m";
  if (seconds < 86400) return String(seconds / 3600) + "h " + String(seconds / 60 % 60) + "m";
  return String(seconds / 86400) + "d";
}

static String petDetails(const Pet& pet, uint32_t now)
{
  if (!connected && !demo) return lastSnapshot ? "Last update " + elapsedLabel((now - lastSnapshot) / 1000) : "No live updates";
  String details;
  if (pet.progressTotal > 0) details = String(pet.progressDone) + "/" + String(pet.progressTotal) + " " + pet.progressKind + " / ";
  details += String(pet.calls) + (pet.calls == 1 ? " tool" : " tools");
  if (pet.helpers) details += " / " + String(pet.helpers) + (pet.helpers == 1 ? " helper" : " helpers");
  if (pet.elapsed >= 0) details += " / " + elapsedLabel(uint32_t(pet.elapsed) + (now - pet.elapsedUpdated) / 1000);
  return details;
}

static void drawInfoBubble(int center, const String& label, const String& title,
                           const String& words, const String& details, uint16_t marker)
{
  int left = constrain(center - 176, 8, 120), top = uiVisible ? 44 : 32, width = 352, height = 126 - top;
  int tail = constrain(center, left + 22, left + width - 22);
  canvas.fillRoundRect(left, top + 3, width, height, 12, UI_SHADOW);
  canvas.fillTriangle(tail - 7, top + height - 1, tail + 7, top + height - 1, tail, top + height + 9, UI_LINE);
  canvas.fillRoundRect(left, top, width, height, 12, UI_SURFACE);
  canvas.drawRoundRect(left, top, width, height, 12, UI_LINE);
  canvas.fillTriangle(tail - 5, top + height - 2, tail + 5, top + height - 2, tail, top + height + 6, UI_SURFACE);
  canvas.fillCircle(left + 16, top + 13, 4, marker);
  canvas.setTextDatum(top_left);
  canvas.setFont(&fonts::Font0); canvas.setTextSize(1.25f);
  canvas.setTextColor(UI_SECONDARY);
  canvas.drawString(label, left + 27, top + 8);
  int statsWidth = width - 41 - canvas.textWidth(label) - 10;
  float statsScale = 1.25f;
  while (statsScale > 1.0f && canvas.textWidth(details) > statsWidth) {
    statsScale -= .125f; canvas.setTextSize(statsScale);
  }
  canvas.setTextDatum(top_right);
  canvas.drawString(fitBubbleText(details, statsWidth), left + width - 14, top + 8);
  canvas.setTextDatum(top_left);
  static String cachedTitle, cachedWords;
  static int cachedHeight = -1;
  static BubbleLayout layout;
  if (cachedTitle != title || cachedWords != words || cachedHeight != height) {
    layout = fitBubbleLayout(title, words, width - 28, height);
    cachedTitle = title; cachedWords = words; cachedHeight = height;
  }
  canvas.setFont(layout.titleFont); canvas.setTextSize(layout.titleScale);
  canvas.setTextColor(UI_INK);
  int textY = top + 21;
  for (int i = 0; i < layout.count; ++i) {
    canvas.drawString(layout.lines[i], left + 14, textY);
    textY += layout.titleHeight + 2;
  }
  canvas.setFont(&fonts::Font2); canvas.setTextSize(layout.statusScale);
  canvas.setTextColor(UI_ACCENT);
  canvas.drawString(fitBubbleText(words, width - 28), left + 14, top + height - 8 - layout.statusHeight);
  // Bubble scaling must not leak into the controls or the next frame.
  canvas.setTextSize(1); canvas.setFont(&fonts::Font2);
}

static void drawPetBubble(uint32_t now)
{
  if (settingsPage || !bubblePet.length() || int32_t(bubbleUntil - now) <= 0) return;
  if (bubblePet == "@connection") {
    String title, words;
    switch (linkState()) {
      case LinkState::Live: title = "All connected"; words = "Your pets are up to date."; break;
      case LinkState::PcOffline: title = "PC disconnected"; words = "Reconnect Bluetooth or plug in USB."; break;
      case LinkState::CompanionOffline: title = "Waiting for companion"; words = "Start Agent Pets on your computer."; break;
      default: title = "Waiting for habitat"; words = "Open the Agent Pets habitat host."; break;
    }
    String transport = bluetoothConnected() ? "Bluetooth / " + String(bluetoothTransport()) : bridgeActive() ? "USB" : "No PC link";
    drawInfoBubble(176, "CONNECTION", title, words, transport, UI_ACCENT);
    return;
  }
  Pet* visible = demo ? demoPets : pets;
  int count = demo ? 3 : petCount;
  const Pet* selected = nullptr;
  for (int i = 0; i < count; ++i) if (visible[i].id == bubblePet) selected = &visible[i];
  if (!selected || (bubbleAutomatic && (!connected || !blocking(selected->attention)))) return;
  const Pet& pet = *selected;
  uint16_t colors[3]; palette(pet.order, colors);
  String label = pet.source == "claude" ? "CLAUDE" : pet.source == "codex" ? "CODEX" : "DEMO";
  drawInfoBubble(petScreenX(pet, now) + 64, label, pet.title, petWords(pet), petDetails(pet, now), colors[0]);
}

bool habitatConnectionInfo()
{
  habitatInteraction();
  if (settingsPage) return false;
  if (bubblePet == "@connection" && int32_t(bubbleUntil - millis()) > 0) bubbleUntil = 0;
  else { bubblePet = "@connection"; bubbleUntil = millis() + PET_INFO_MS; bubbleAutomatic = false; }
  return true;
}

bool habitatInspect(int index)
{
  habitatInteraction();
  if (settingsPage || index < 0 || index >= (demo ? 3 : petCount)) return false;
  Pet& pet = (demo ? demoPets : pets)[index];
  if (bubblePet == pet.id && int32_t(bubbleUntil - millis()) > 0 && !bubbleAutomatic) bubbleUntil = 0;
  else showBubble(pet, false);
  return true;
}

static bool inspectAt(int x, int y, uint32_t now)
{
  if (y < PET_TOP - 8 || y >= PET_TOP + 128) return false;
  Pet* visible = demo ? demoPets : pets;
  int count = demo ? 3 : petCount;
  for (int i = 0; i < count; ++i) {
    int left = petScreenX(visible[i], now);
    if (x >= left - 6 && x < left + 134) return habitatInspect(i);
  }
  return false;
}

static void loadBackdrop()
{
  drawRle(backdrop, artBackdrops[scenery].offset, 480, 280, 0, 0, 480, nullptr, 320);
}

static void drawAmbientStatus(int extra)
{
  auto background = canvas.readPixelRGB(20, 20);
  LinkState state = linkState();
  bool live = state == LinkState::Live && !demo;
  bool pcOffline = state == LinkState::PcOffline && !demo;
  uint8_t red = live ? 64 : pcOffline ? 138 : 204;
  uint8_t green = live ? 151 : pcOffline ? 154 : 137;
  uint8_t blue = live ? 120 : pcOffline ? 145 : 83;
  uint16_t ink = canvas.color565((background.r + red) / 2,
                                (background.g + green) / 2,
                                (background.b + blue) / 2);
  canvas.drawCircle(20, 20, 5, ink);
  if (demo) canvas.fillTriangle(18, 17, 18, 23, 23, 20, ink);
  else if (live) canvas.fillCircle(20, 20, 2, ink);
  else if (state == LinkState::PcOffline) canvas.drawLine(17, 23, 23, 17, ink);
  else if (state == LinkState::CompanionOffline) {
    canvas.drawLine(18, 18, 18, 22, ink);
    canvas.drawLine(22, 18, 22, 22, ink);
  } else canvas.drawRect(18, 18, 5, 5, ink);
  if (extra) {
    canvas.setFont(&fonts::Font0);
    canvas.setTextDatum(middle_left);
    canvas.setTextColor(ink);
    canvas.drawString("+" + String(extra), 32, 20);
  }
}

static void drawControl(int index, int x, int width, const char* label, const char* value, bool selected)
{
  bool pressed = pressedControl == index && int32_t(pressedUntil - millis()) > 0;
  int y = pressed ? 273 : 271;
  canvas.fillRoundRect(x, 274, width, 40, 10, UI_SHADOW);
  uint16_t fill = selected ? UI_ACCENT : pressed ? UI_PRESSED : UI_SURFACE;
  uint16_t ink = selected ? UI_SURFACE : UI_INK;
  canvas.fillRoundRect(x, y, width, 40, 10, fill);
  canvas.drawRoundRect(x, y, width, 40, 10, selected ? UI_ACCENT : UI_LINE);
  canvas.setTextDatum(top_left);
  canvas.setFont(&fonts::Font0);
  canvas.setTextColor(selected ? UI_PRESSED : UI_SECONDARY);
  canvas.drawString(label, x + 12, y + 6);
  canvas.setFont(&fonts::Font2);
  canvas.setTextColor(ink);
  canvas.drawString(value, x + 12, y + 17);
  int arrowX = x + width - 15;
  canvas.drawLine(arrowX - 3, y + 20, arrowX, y + 23, ink);
  canvas.drawLine(arrowX, y + 23, arrowX - 3, y + 26, ink);
}

static void drawSettingsControl()
{
  bool pressed = pressedControl == 3 && int32_t(pressedUntil - millis()) > 0;
  canvas.fillRoundRect(430, 11, 42, 42, 12, UI_SHADOW);
  canvas.fillRoundRect(430, 8, 42, 42, 12, pressed ? UI_PRESSED : UI_SURFACE);
  canvas.drawRoundRect(430, 8, 42, 42, 12, UI_LINE);
  for (int i = 0; i < 8; ++i) {
    float angle = i * PI / 4;
    canvas.fillCircle(451 + cosf(angle) * 11, 29 + sinf(angle) * 11, 3, UI_INK);
  }
  canvas.fillCircle(451, 29, 11, UI_INK);
  canvas.fillCircle(451, 29, 5, UI_SURFACE);
}

static void settingsButton(int x, int y, int width, const String& label, bool primary = true)
{
  canvas.fillRoundRect(x, y + 3, width, 38, 10, UI_SHADOW);
  canvas.fillRoundRect(x, y, width, 38, 10, primary ? UI_ACCENT : UI_SURFACE);
  canvas.drawRoundRect(x, y, width, 38, 10, primary ? UI_ACCENT : UI_LINE);
  canvas.setFont(&fonts::Font2);
  canvas.setTextDatum(middle_center);
  canvas.setTextColor(primary ? UI_SURFACE : UI_INK);
  canvas.drawString(label, x + width / 2, y + 19);
}

uint8_t habitatBrightness()
{
  return (uint16_t(brightness) * 100 + 127) / 255;
}

void habitatSetBrightness(int percent, bool save)
{
  brightness = (constrain(percent, 1, 100) * 255 + 50) / 100;
  applyPowerBrightness();
  if (save) preferences.putUChar("brightness", brightness);
}

void habitatSettings(int page)
{
  habitatInteraction();
  settingsPage = constrain(page, 0, 4);
  redrawRequested = true;
  uiVisible = true;
  lastUiTouch = millis();
}

static void drawSettings()
{
  canvas.fillScreen(UI_PAPER);
  canvas.fillRect(140, 66, 328, 242, UI_SURFACE);
  canvas.drawFastHLine(16, 60, 448, UI_LINE);
  canvas.setTextDatum(top_left);
  canvas.setFont(&fonts::Font4);
  canvas.setTextColor(UI_INK);
  canvas.drawString("Settings", 22, 19);
  canvas.fillRoundRect(424, 12, 42, 38, 10, UI_SURFACE);
  canvas.drawLine(439, 25, 451, 37, UI_INK);
  canvas.drawLine(451, 25, 439, 37, UI_INK);
  settingsButton(14, 82, 112, "Audio", settingsPage == 1);
  settingsButton(14, 134, 112, "Bluetooth", settingsPage == 2);
  settingsButton(14, 186, 112, "Display", settingsPage == 3);
  settingsButton(14, 238, 112, "Battery", settingsPage == 4);
  canvas.setTextDatum(top_left);
  canvas.setFont(&fonts::Font0);
  canvas.setTextColor(UI_SECONDARY);
  canvas.drawString("AGENT PETS", 22, 292);
  canvas.setFont(&fonts::Font2);
  if (settingsPage == 1) {
    canvas.drawString("Sounds and voice", 162, 82);
    canvas.setTextColor(UI_INK);
    canvas.drawString("Mute", 162, 118);
    bool quiet = buttonAudioMuted();
    canvas.fillRoundRect(386, 114, 48, 24, 12, quiet ? UI_ACCENT : UI_LINE);
    canvas.fillCircle(quiet ? 422 : 398, 126, 9, UI_SURFACE);
    canvas.drawString("Voice", 162, 158);
    bool speaking = buttonAudioVoiceEnabled();
    canvas.fillRoundRect(386, 154, 48, 24, 12, speaking ? UI_ACCENT : UI_LINE);
    canvas.fillCircle(speaking ? 422 : 398, 166, 9, UI_SURFACE);
    canvas.drawString("Volume", 162, 194);
    canvas.setTextDatum(top_right);
    canvas.drawString(String(buttonAudioVolume()) + "%", 438, 194);
    canvas.fillRoundRect(172, 230, 256, 6, 3, UI_LINE);
    int thumb = 172 + buttonAudioVolume() * 256 / 100;
    canvas.fillRoundRect(172, 230, max(6, thumb - 172), 6, 3, UI_ACCENT);
    canvas.fillCircle(thumb, 233, 11, UI_SHADOW);
    canvas.fillCircle(thumb, 231, 10, UI_SURFACE);
    canvas.drawCircle(thumb, 231, 10, UI_ACCENT);
    settingsButton(162, 258, 276, buttonAudioReady() ? (speaking ? "Test voice" : "Test sound") : "Audio unavailable");
  } else if (settingsPage == 3) {
    canvas.drawString("Screen and power", 162, 82);
    canvas.setTextColor(UI_INK);
    canvas.drawString("Brightness", 162, 114);
    canvas.setTextDatum(top_right);
    canvas.drawString(String(habitatBrightness()) + "%", 438, 114);
    canvas.fillRoundRect(172, 150, 256, 6, 3, UI_LINE);
    int thumb = 172 + (habitatBrightness() - 1) * 256 / 99;
    canvas.fillRoundRect(172, 150, max(6, thumb - 172), 6, 3, UI_ACCENT);
    canvas.fillCircle(thumb, 153, 11, UI_SHADOW);
    canvas.fillCircle(thumb, 151, 10, UI_SURFACE);
    canvas.drawCircle(thumb, 151, 10, UI_ACCENT);
    settingsButton(162, 190, 276, idleMinutes ? "Screen off: " + String(idleMinutes) + " min" : "Screen off: never", false);
    bool confirming = int32_t(deepConfirmUntil - millis()) > 0;
    settingsButton(162, 248, 276, confirming ? "Tap again to sleep" : "Deep sleep", false);
    canvas.setTextDatum(top_left); canvas.setFont(&fonts::Font0);
    canvas.setTextColor(UI_SECONDARY);
    canvas.drawString(confirming ? "Only the BOOT button wakes deep sleep." : "Eco mode / tap to change idle timeout", 162, 292);
  } else if (settingsPage == 4) {
    canvas.drawString("Battery",162,82);
    canvas.setTextColor(UI_INK);canvas.drawString("Installed",162,118);
    canvas.fillRoundRect(386,114,48,24,12,batteryInstalled?UI_ACCENT:UI_LINE);
    canvas.fillCircle(batteryInstalled?422:398,126,9,UI_SURFACE);
    if(batteryInstalled) {
      canvas.drawString("About "+String(batteryLevel(batteryMv))+"%",162,164);
      char volts[12];snprintf(volts,sizeof(volts),"%u.%02u V",batteryMv/1000,batteryMv%1000/10);
      canvas.drawString(volts,162,195);
    }
    canvas.setFont(&fonts::Font0);canvas.setTextColor(UI_SECONDARY);
    canvas.drawString("Enable when a battery is fitted.",162,240);
    canvas.drawString("Turn off when you remove it.",162,256);
    canvas.drawString("Charge is estimated from voltage.",162,280);
  } else {
    canvas.setTextColor(UI_INK);
    canvas.drawString(bluetoothName(), 162, 82);
    canvas.setTextColor(UI_SECONDARY);
    unsigned seconds = bluetoothPairSeconds();
    String status = seconds ? "Ready to pair - " + String(seconds) + "s"
                    : !bluetoothBonded() ? "No paired PC" : linkState() == LinkState::Live
                    ? "Live via " + String(bluetoothSource ? bluetoothTransport() : "USB") : String(linkLabel());
    canvas.drawString(status, 162, 113);
    settingsButton(162, 154, 276, seconds ? "Cancel pairing" : "Pair PC");
    bool confirming = int32_t(forgetUntil - millis()) > 0;
    settingsButton(162, 206, 276, confirming ? "Tap again to forget PCs" : "Forget paired PCs", false);
    canvas.setTextDatum(top_left);
    canvas.setFont(&fonts::Font0);
    canvas.setTextColor(UI_SECONDARY);
    const char* hint = "PC and companion connected.";
    const char* detail = "Backend is live.";
    if (seconds) { hint = "Open Bluetooth settings on your computer."; detail = "Add device > Agent Pets"; }
    else if (linkState() == LinkState::PcOffline) { hint = "Reconnect your computer over Bluetooth."; detail = "Pairing stays saved."; }
    else if (linkState() == LinkState::CompanionOffline) { hint = "PC connected. Companion is not running."; detail = "Start the Agent Pets companion."; }
    else if (linkState() == LinkState::BackendOffline) { hint = "Companion connected. Backend not found."; detail = "Start the Agent Pets habitat backend."; }
    canvas.drawString(hint, 162, 264);
    canvas.drawString(detail, 162, 280);
  }
}

void habitatPowerMenu(bool visible)
{
  habitatInteraction(); powerMenu=visible; bubbleUntil=0; redrawRequested=true;
}

static void drawPowerMenu()
{
  canvas.fillScreen(UI_PAPER);
  canvas.drawCircle(240,76,19,UI_ACCENT);
  canvas.drawCircle(240,76,18,UI_ACCENT);
  canvas.fillRect(234,54,13,10,UI_PAPER);
  canvas.fillRect(238,52,4,25,UI_ACCENT);
  canvas.setFont(&fonts::Font4);canvas.setTextDatum(middle_center);canvas.setTextColor(UI_INK);
  canvas.drawString("Power",240,122);
  settingsButton(112,162,256,"Deep sleep");
  settingsButton(112,216,256,"Cancel",false);
  canvas.setFont(&fonts::Font0);canvas.setTextDatum(middle_center);canvas.setTextColor(UI_SECONDARY);
  canvas.drawString("Press BOOT to wake after deep sleep.",240,284);
  canvas.setTextDatum(top_left);
}

static void render()
{
  ++renderedFrames;
  uint32_t now = millis();
  backdrop.pushSprite(&canvas, 0, 0);
  int count = demo ? 3 : petCount;
  Pet* visible = demo ? demoPets : pets;
  if (!count) { count = 1; visible = &resting; resting.targetX = slotX(0, 1); }
  canvas.setFont(&fonts::Font2);
  for (int i = 0; i < count; ++i) {
    Pet& pet = visible[i];
    String pose = poseFor(pet, now);
    if (pose != pet.lastPose) { pet.lastPose = pose; pet.poseSince = now; }
    int x = petScreenX(pet, now);
    int petTop = drawPet(pet, pose, x, PET_TOP, 128, now - pet.poseSince);
    if (pet.moment == "forked" && int32_t(pet.momentUntil - now) > 0 && !blocking(pet.attention)) {
      float progress = 1 - (pet.momentUntil - now) / 1450.0f;
      drawPet(pet, pose, x + 48 * progress, PET_TOP - 24 * progress, 84, now - pet.poseSince);
    }
    if (pet.helpers > 0 && (demo || connected)) {
      drawPet(pet, "helper", x + 88, PET_TOP + 88, 40, now - pet.poseSince);
      if (pet.helpers > 1) {
        canvas.setTextDatum(bottom_right);
        canvas.setTextColor(0x3268);
        canvas.drawString(String(pet.helpers), x + 124, PET_TOP + 133);
      }
    }
    if (pet.attention != "none" && (demo || connected)) {
      uint32_t icon = icon_ready;
      if (pet.attention == "approval") icon = icon_approval;
      if (pet.attention == "question") icon = icon_question;
      if (pet.attention == "failure") icon = icon_failure;
      // Keep every signal above the visible sprite, including taller characters.
      int badgeY = petTop - 34;
      canvas.fillRoundRect(x + 51, badgeY, 26, 26, 5, pet.attention == "ready" ? 0xDF7A : 0xFF99);
      canvas.drawRoundRect(x + 51, badgeY, 26, 26, 5, 0x3268);
      drawRle(canvas, icon, 16, 16, x + 56, badgeY + 5, 16, nullptr);
    }
  }
  for (auto& departure : departures) {
    uint32_t age = now - departure.started;
    uint32_t duration = departure.closed ? 3000 : 650;
    if (departure.started && age < duration && !demo)
      drawPet(departure.pet, departure.closed ? "departing" : "walking",
              departure.pet.targetX + (departure.closed ? 0 : age * 80 / 650), PET_TOP, 128, age);
  }
  int extra = demo ? 1 : max(0, totalPets - petCount);
  if (uiVisible) {
    canvas.setTextDatum(top_left);
    canvas.setTextColor(UI_INK);
    canvas.fillRoundRect(12, 15, 186, 28, 12, UI_SHADOW);
    canvas.fillRoundRect(12, 12, 186, 28, 12, UI_SURFACE);
    uint16_t statusColor = connected && !demo ? UI_ACCENT : linkState() == LinkState::PcOffline && !demo
                          ? uiColor(0x8A9A91) : uiColor(0xC29550);
    canvas.fillCircle(25, 26, 4, statusColor);
    canvas.drawString(demo ? "Demo" : linkLabel(), 36, 18);
    if (clockKnown && !settingsPage) {
      uint32_t seconds = (clockSeconds + (now - clockUpdated) / 1000) % 86400;
      char clockText[6]; snprintf(clockText, sizeof(clockText), "%02u:%02u", unsigned(seconds / 3600), unsigned(seconds / 60 % 60));
      canvas.fillRoundRect(210, 12, 72, 28, 12, UI_SURFACE);
      canvas.setFont(&fonts::Font2); canvas.setTextDatum(middle_center);
      canvas.drawString(clockText, 246, 26);
      canvas.setTextDatum(top_left);
    }
    if (extra) {
      canvas.fillRoundRect(383, 12, 38, 28, 9, UI_SURFACE);
      drawRle(canvas, icon_overflow, 16, 16, 387, 18, 16, nullptr);
      canvas.setTextDatum(top_right);
      canvas.drawString(String(extra), 417, 18);
    }
    drawSettingsControl();
    canvas.fillRect(0, 263, 480, 57, UI_PAPER);
    canvas.drawFastHLine(0, 263, 480, UI_LINE);
    drawControl(0, 8, 152, "CHARACTER", artCharacters[character].name, false);
    drawControl(1, 168, 196, "HABITAT", artBackdrops[scenery].name, false);
    drawControl(2, 372, 100, "MODE", demo ? "Demo" : "Live", demo);
    if (settingsPage) drawSettings();
  } else {
    drawAmbientStatus(extra);
  }
  drawPetBubble(now);
  drawBattery();
  if(powerMenu) drawPowerMenu();
  // ST77922 hardware rotation differs from the inherited ST77916 mapping.
  // Rotate the finished scene into the opposite landscape placement on the 320x480 panel.
  const uint16_t* source = static_cast<const uint16_t*>(canvas.getBuffer());
  uint16_t* destination = static_cast<uint16_t*>(panelCanvas.getBuffer());
  for (int panelY = 0; panelY < 480; ++panelY) {
    for (int panelX = 0; panelX < 320; ++panelX)
      destination[panelY * 320 + panelX] = source[panelX * 480 + (479 - panelY)];
  }
  panelCanvas.pushSprite(0, 0);
}

void habitatBegin()
{
  lcd.init();
  lcd.setRotation(0);
  lcd.setBrightness(0); // Restore the saved level before the first frame.
  canvas.setPsram(true);
  canvas.setColorDepth(16);
  backdrop.setPsram(true);
  backdrop.setColorDepth(16);
  panelCanvas.setPsram(true);
  panelCanvas.setColorDepth(16);
  if (!canvas.createSprite(480, 320) || !backdrop.createSprite(480, 320) ||
      !panelCanvas.createSprite(320, 480)) {
    Serial.println("PSRAM allocation failed");
    while (true) delay(1000);
  }
  preferences.begin("habitat", false);
  batteryInstalled=preferences.getBool("battery",false);
  readBattery();
  pinMode(0, INPUT_PULLUP);
  idleMinutes = preferences.getUChar("idlemins", 5);
  if (idleMinutes != 0 && idleMinutes != 1 && idleMinutes != 5 && idleMinutes != 15 && idleMinutes != 30) idleMinutes = 5;
  powerPolicy.timeout = uint32_t(idleMinutes) * 60000;
  powerPolicy.last = millis();
  brightness = constrain(preferences.getUChar("brightness", 200), 3, 255);
  lcd.setBrightness(brightness);
  character = preferences.getUChar("character", 0) % (sizeof(artCharacters) / sizeof(artCharacters[0]));
  scenery = preferences.getUChar("scenery", 1) % (sizeof(artBackdrops) / sizeof(artBackdrops[0]));
  buttonAudioBegin(preferences.getBool("muted", false), preferences.getUChar("volume", 40));
  buttonAudioVoice(preferences.getBool("voice", false));
  buttonAudioReport();
  loadBackdrop();
  resting.activity = "resting";
  resting.attention = "none";
  for (int i = 0; i < 3; ++i) {
    demoPets[i].id = "demo" + String(i);
    demoPets[i].order = i;
    demoPets[i].title = "Demo pet " + String(i + 1);
    demoPets[i].attention = "none";
    demoPets[i].activity = i == 0 ? "editing" : i == 1 ? "researching" : "idle";
    demoPets[i].targetX = slotX(i, 3);
    demoPets[i].calls = i == 1 ? 2 : 0;
    demoPets[i].helpers = i == 0 ? 2 : 0;
  }
}

void habitatTick()
{
  uint32_t now = millis();
  static BootGesture boot;
  static bool bootWakeConsumed=false;
  BootGesture::Event event=boot.update(digitalRead(0)==LOW,now);
  if(event==BootGesture::Pressed) {
    bootWakeConsumed=powerPolicy.stage!=PowerPolicy::Stage::Eco;
    habitatInteraction();
  } else if(event==BootGesture::ShortPress && !bootWakeConsumed) {
    habitatInteraction(); powerMenu=false; uiVisible=true; lastUiTouch=millis(); redrawRequested=true;
  } else if(event==BootGesture::LongPress) {
    habitatPowerMenu(true);
  }
  if(boot.down) habitatInteraction();
  connected = linkState() == LinkState::Live;
  readBattery();
  static bool wasTouched = false;
  static uint32_t lastButtonTouch = 0;
  int32_t x = 0, y = 0;
  bool touched = lcd.getTouch(&x, &y);
  int32_t nativeX = x;
  x = 479 - y;
  y = nativeX;
  if (touched) {
    bool wasSleeping = powerPolicy.stage != PowerPolicy::Stage::Eco;
    habitatInteraction();
    if (wasSleeping) wakeTouchGuard = true;
  }
  if (!touched) wakeTouchGuard = false;
  bool firstTouch = touched && !wasTouched && !wakeTouchGuard && now - lastButtonTouch >= 160;
  if (touched) redrawRequested = true;
  if (touched && uiVisible) lastUiTouch = now;
  if (uiVisible && !settingsPage && !touched && now - lastUiTouch >= UI_IDLE_MS) {
    uiVisible = false;
  }
  if (powerMenu) {
    if(firstTouch) {
      lastButtonTouch=now;
      if(x>=112 && x<=368 && y>=162 && y<=202) habitatDeepSleep();
      else if(x>=112 && x<=368 && y>=216 && y<=256) habitatPowerMenu(false);
    }
  } else if (firstTouch && !settingsPage && x >= 0 && x <= (uiVisible ? 198 : 44) && y >= 0 && y <= 44) {
    habitatConnectionInfo(); lastButtonTouch = now;
  } else if (firstTouch && !settingsPage && inspectAt(x, y, now)) {
    lastButtonTouch = now;
  } else if (firstTouch && !settingsPage && int32_t(bubbleUntil - now) > 0 && y >= (uiVisible ? 44 : 32) && y < 136) {
    bubbleUntil = 0;
    lastButtonTouch = now;
  } else if (firstTouch && !uiVisible) {
    // Consume the reveal gesture so tapping over a hidden control cannot activate it.
    uiVisible = true;
    lastUiTouch = lastButtonTouch = now;
  } else if (uiVisible && settingsPage) {
    if (firstTouch) {
      lastButtonTouch = now;
      if (x >= 424 && y <= 54) {
        settingsPage = 0;
        buttonAudioPlay();
      } else if (x >= 14 && x <= 126 && y >= 82 && y <= 122) {
        settingsPage = 1;
        buttonAudioPlay();
      } else if (x >= 14 && x <= 126 && y >= 134 && y <= 174) {
        settingsPage = 2;
        buttonAudioPlay();
      } else if (x >= 14 && x <= 126 && y >= 186 && y <= 226) {
        settingsPage = 3;
        buttonAudioPlay();
      } else if (x >= 14 && x <= 126 && y >= 238 && y <= 278) {
        settingsPage = 4; readBattery(); buttonAudioPlay();
      } else if (settingsPage == 4 && x >= 366 && x <= 454 && y >= 102 && y <= 148) {
        habitatBatteryInstalled(!batteryInstalled); buttonAudioPlay();
      } else if (settingsPage == 3 && x >= 152 && x <= 448 && y >= 132 && y <= 174) {
        adjustingBrightness = true;
      } else if (settingsPage == 3 && x >= 162 && x <= 438 && y >= 190 && y <= 230) {
        const uint8_t choices[] = {1,5,15,30,0};
        for (int i=0;i<5;++i) if (choices[i]==idleMinutes) { idleMinutes=choices[(i+1)%5]; break; }
        preferences.putUChar("idlemins",idleMinutes);
        powerPolicy.timeout=uint32_t(idleMinutes)*60000;
        buttonAudioPlay();
      } else if (settingsPage == 3 && x >= 162 && x <= 438 && y >= 248 && y <= 288) {
        if (int32_t(deepConfirmUntil-now)>0) habitatDeepSleep();
        else deepConfirmUntil=now+5000;
      } else if (settingsPage == 1 && x >= 366 && x <= 454 && y >= 102 && y <= 148) {
        buttonAudioMute(!buttonAudioMuted());
        preferences.putBool("muted", buttonAudioMuted());
        buttonAudioPlay();
      } else if (settingsPage == 1 && x >= 366 && x <= 454 && y >= 150 && y <= 184) {
        buttonAudioVoice(!buttonAudioVoiceEnabled());
        preferences.putBool("voice", buttonAudioVoiceEnabled());
        buttonAudioPlay();
      } else if (settingsPage == 1 && x >= 152 && x <= 448 && y >= 214 && y <= 250) {
        adjustingVolume = true;
      } else if (settingsPage == 1 && x >= 162 && x <= 438 && y >= 258 && y <= 298) {
        if (buttonAudioVoiceEnabled()) buttonAudioSpeak(PetVoice::Ready);
        else buttonAudioPlay();
      } else if (settingsPage == 2 && x >= 162 && x <= 438 && y >= 154 && y <= 194) {
        if (bluetoothPairSeconds()) bluetoothCancelPair();
        else bluetoothPair();
        buttonAudioPlay();
      } else if (settingsPage == 2 && x >= 162 && x <= 438 && y >= 206 && y <= 246) {
        if (int32_t(forgetUntil - now) > 0) { bluetoothForget(); forgetUntil = 0; }
        else forgetUntil = now + 5000;
        buttonAudioPlay();
      }
    }
    if (adjustingVolume && touched)
      buttonAudioSetVolume(constrain((x - 172) * 100 / 256, 0, 100));
    if (adjustingBrightness && touched && !wakeTouchGuard)
      habitatSetBrightness(1 + constrain((x - 172) * 99 / 256, 0, 99), false);
  } else if (uiVisible && firstTouch) {
    int control = -1;
    if (x >= 426 && y <= 54) control = 3;
    else if (y >= 263) control = x < 164 ? 0 : x < 368 ? 1 : 2;
    if (control >= 0) {
      lastButtonTouch = now;
      pressedControl = control;
      pressedUntil = now + 180;
    }
    if (control == 0) {
      character = (character + 1) % (sizeof(artCharacters) / sizeof(artCharacters[0]));
      preferences.putUChar("character", character);
    } else if (control == 1) {
      scenery = (scenery + 1) % (sizeof(artBackdrops) / sizeof(artBackdrops[0]));
      preferences.putUChar("scenery", scenery);
      loadBackdrop();
    } else if (control == 2) { demo = !demo; bubbleUntil = 0; }
    else if (control == 3) {
      settingsPage = 1;
      bubbleUntil = 0;
    }
    if (control >= 0) buttonAudioPlay();
    else uiVisible = false;
  }
  if (!touched && wasTouched && adjustingVolume) {
    adjustingVolume = false;
    preferences.putUChar("volume", buttonAudioVolume());
    buttonAudioPlay();
  }
  if (!touched && wasTouched && adjustingBrightness) {
    adjustingBrightness = false;
    preferences.putUChar("brightness", brightness);
    buttonAudioPlay();
  }
  wasTouched = touched;
  if (demo) demoPets[2].attention = now / 6000 % 2 ? "ready" : "approval";
  now = millis(); // Wake and input handlers may have advanced time.
  PowerPolicy::Stage previous = powerPolicy.stage;
  powerPolicy.tick(now);
  if (previous != powerPolicy.stage) {
    redrawRequested = true;
    if (habitatScreenOff()) {
      // The integrated touch controller stops reporting during LCD SLPIN.
      // Keep it scanning in connected screen-off; sleep the panel only in deep sleep.
      lcd.setBrightness(0);
      buttonAudioSleep(true); uiVisible = false; settingsPage = 0; bubbleUntil = 0; powerMenu = false;
    }
    habitatPowerReport();
  }
  static uint32_t lastFrame = 0;
  if (!habitatScreenOff() && (redrawRequested || now-lastFrame >= uint32_t(touched?60:settingsPage?1000:125))) {
    lastFrame=now; render(); redrawRequested=false;
  }
  applyPowerBrightness();
}

void habitatAudioTest()
{
  habitatInteraction();
  buttonAudioPlay();
  buttonAudioReport();
}

void habitatCapture()
{
  uint8_t* pixels = static_cast<uint8_t*>(ps_malloc(480 * 320 * 3));
  if (!pixels) return;
  canvas.readRectRGB(0, 0, 480, 320, pixels);
  Serial.println("{\"event\":\"capture\",\"bytes\":460800}");
  Serial.write(pixels, 480 * 320 * 3);
  free(pixels);
}

void habitatPowerTest(uint32_t timeout, uint32_t warning)
{
  habitatInteraction(); powerPolicy.timeout=timeout; powerPolicy.warning=warning;
}

bool habitatDeepSleep(uint32_t testWakeSeconds)
{
  if (digitalRead(0)==LOW) return false; // Do not arm an already-held wake button.
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
  if (esp_sleep_enable_ext1_wakeup_io(1ULL, ESP_EXT1_WAKEUP_ANY_LOW)!=ESP_OK) return false;
  if (testWakeSeconds) esp_sleep_enable_timer_wakeup(uint64_t(testWakeSeconds)*1000000ULL);
  buttonAudioSleep(true);
  uint32_t start=millis();
  while (!buttonAudioSleeping() && millis()-start<2000) delay(10);
  if (!buttonAudioSleeping()) { buttonAudioSleep(false); return false; }
  lcd.setBrightness(0); lcd.sleep();
  bluetoothSleep();
  pinMode(41,OUTPUT); digitalWrite(41,LOW);
  pinMode(1,OUTPUT); digitalWrite(1,HIGH);
  gpio_hold_en(GPIO_NUM_41); gpio_hold_en(GPIO_NUM_1); gpio_deep_sleep_hold_en();
  Serial.println("{\"event\":\"deep_sleep\",\"wake\":\"BOOT\"}");
  Serial.flush(); delay(30); esp_deep_sleep_start();
  return true;
}
