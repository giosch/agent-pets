#include <Arduino.h>
#include <atomic>
#include <math.h>
#define LGFX_USE_V1
#include <LovyanGFX.hpp>
#include <driver/i2s_std.h>
#include "button_audio.h"
#include "device_voice.h"

// ES3C35P codec and amplifier wiring, verified against the board reference.
// Clock/format settings follow Espressif's ES8311 driver for 24 kHz, 256x MCLK.
// https://github.com/espressif/esp-bsp/tree/master/components/es8311
// Analog bias/reference startup follows esp-adf's esp_codec_dev ES8311 sequence.
// https://github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es8311/es8311.c
static constexpr int AMPLIFIER_PIN = 1; // Active low.
static constexpr int SAMPLE_RATE = 24000;
static constexpr int TONE_FRAMES = SAMPLE_RATE * 60 / 1000;
static i2s_chan_handle_t channel = nullptr;
static QueueHandle_t clicks = nullptr;
static std::atomic<bool> muted{false}, voiceEnabled{false}, previewMuted{false};
static std::atomic<uint8_t> volume{40};
static std::atomic<int> lastWriteResult{ESP_OK};
static std::atomic<uint32_t> lastWriteBytes{0};
static bool ready = false;

static bool codecWrite(uint8_t reg, uint8_t value)
{
  const uint8_t bytes[] = {reg, value};
  // Share LovyanGFX's existing I2C controller with touch, using its bus locking.
  return lgfx::i2c::transactionWrite(1, 0x18, bytes, sizeof(bytes), 100000).has_value();
}

static void playVoice(uint8_t clipIndex)
{
  if (clipIndex >= sizeof(petVoiceClips) / sizeof(petVoiceClips[0])) return;
  static const int steps[] = {7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767};
  static const int changes[] = {-1,-1,-1,-1,2,4,6,8};
  const PetVoiceClip& clip = petVoiceClips[clipIndex];
  int predictor = 0, index = 0, previous = 0;
  int16_t samples[256 * 4];
  for (uint32_t position = 0; position < clip.samples;) {
    if (muted.load() || previewMuted.load() || !voiceEnabled.load() || !volume.load()) return;
    float gain = powf(10.0f, (-70.0f + 70.0f * volume.load() / 100.0f) / 20.0f);
    int count = 0;
    for (int n = 0; n < 256 && position < clip.samples; ++n, ++position) {
      int code = (clip.data[position / 2] >> ((position % 2) * 4)) & 15;
      int step = steps[index], delta = step >> 3;
      if (code & 4) delta += step;
      if (code & 2) delta += step >> 1;
      if (code & 1) delta += step >> 2;
      predictor = constrain(predictor + (code & 8 ? -delta : delta), -32768, 32767);
      index = constrain(index + changes[code & 7], 0, 88);
      // Linear 12 -> 24 kHz upsampling into the codec's existing stereo stream.
      int16_t midpoint = lroundf((previous + predictor) * .5f * gain);
      int16_t current = lroundf(predictor * gain);
      samples[count++] = midpoint; samples[count++] = midpoint;
      samples[count++] = current; samples[count++] = current;
      previous = predictor;
    }
    size_t written = 0;
    esp_err_t result = i2s_channel_write(channel, samples, count * sizeof(int16_t), &written, 100);
    lastWriteResult.store(result); lastWriteBytes.store(written);
    if (result != ESP_OK) return;
  }
}

static void playClicks(void*)
{
  uint8_t click;
  static int16_t tone[TONE_FRAMES];
  static int16_t samples[TONE_FRAMES * 2];
  int peak = 0;
  // Normalize the enveloped note so 100% reaches the 16-bit full-scale peak.
  for (int i = 0; i < TONE_FRAMES; ++i) {
    float envelope = .5f - .5f * cosf(2 * PI * i / (TONE_FRAMES - 1));
    tone[i] = lroundf(INT16_MAX * envelope * sinf(2 * PI * 1100 * i / SAMPLE_RATE));
    peak = max(peak, abs(int(tone[i])));
  }
  for (int i = 0; i < TONE_FRAMES; ++i)
    tone[i] = int32_t(tone[i]) * INT16_MAX / peak;
  while (true) {
    xQueueReceive(clicks, &click, portMAX_DELAY);
    if (muted.load() || previewMuted.load() || volume.load() == 0) continue;
    if (click >= 2) { playVoice(click - 2); continue; }
    // A -70 to 0 dBFS curve keeps the lower settings quiet while allowing
    // full digital range at the top. Zero volume is handled as silence above.
    float decibels = -70.0f + 70.0f * volume.load() / 100.0f;
    float gain = powf(10.0f, decibels / 20.0f);
    for (int i = 0; i < TONE_FRAMES; ++i) {
      int16_t sample = lroundf(tone[i] * gain);
      samples[i * 2] = samples[i * 2 + 1] = sample;
    }
    size_t written = 0;
    esp_err_t result = i2s_channel_write(channel, samples, sizeof(samples), &written, 100);
    lastWriteResult.store(result);
    lastWriteBytes.store(written);
    // I2S automatically sends zeros between notes. Keeping the amplifier awake
    // avoids the standby transitions that produce a pop on every button tap.
  }
}

bool buttonAudioBegin(bool initiallyMuted, uint8_t initialVolume)
{
  muted.store(initiallyMuted);
  volume.store(min(uint8_t(100), initialVolume));
  pinMode(AMPLIFIER_PIN, OUTPUT);
  digitalWrite(AMPLIFIER_PIN, HIGH);
  // Probe before allocating I2S resources. The display is already initialized.
  if (!codecWrite(0x00, 0x1F)) return false;
  delay(20);
  if (!codecWrite(0x00, 0x00)) return false;
  i2s_chan_config_t channelConfig = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
  channelConfig.auto_clear_after_cb = true;
  if (i2s_new_channel(&channelConfig, &channel, nullptr) != ESP_OK) return false;
  i2s_std_config_t config = {};
  config.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE);
  config.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  config.gpio_cfg.mclk = GPIO_NUM_17;
  config.gpio_cfg.bclk = GPIO_NUM_18;
  config.gpio_cfg.ws = GPIO_NUM_21;
  config.gpio_cfg.dout = GPIO_NUM_15;
  config.gpio_cfg.din = I2S_GPIO_UNUSED;
  bool enabled = false;
  bool valid = i2s_channel_init_std_mode(channel, &config) == ESP_OK;
  if (valid) {
    enabled = i2s_channel_enable(channel) == ESP_OK;
    valid = enabled;
  }
  // External 6.144 MHz MCLK, slave I2S, 16-bit samples, DAC output enabled.
  const uint8_t registers[][2] = {
    {0x0D, 0xFA}, {0x44, 0x08}, {0x44, 0x08},
    {0x0B, 0x00}, {0x0C, 0x00}, {0x10, 0x1F}, {0x11, 0x7F},
    {0x00, 0x80}, {0x01, 0x3F}, {0x02, 0x00}, {0x03, 0x10},
    {0x04, 0x10}, {0x05, 0x00}, {0x06, 0x03}, {0x07, 0x00},
    {0x08, 0xFF}, {0x09, 0x0C}, {0x0A, 0x0C}, {0x0D, 0x01},
    {0x0E, 0x02}, {0x12, 0x00}, {0x13, 0x10}, {0x1C, 0x6A},
    {0x14, 0x1A}, {0x15, 0x40}, {0x45, 0x00},
    {0x37, 0x08}, {0x32, 0xBF} // ES8311 unity gain is 0xBF. 0xFF adds 32 dB.
  };
  for (const auto& setting : registers) {
    if (valid) valid = codecWrite(setting[0], setting[1]);
  }
  if (valid) valid = codecWrite(0x31, initiallyMuted ? 0x60 : 0x00);
  if (valid) {
    clicks = xQueueCreate(1, sizeof(uint8_t));
    valid = clicks != nullptr;
  }
  if (valid) valid = xTaskCreate(playClicks, "button-audio", 8192, nullptr, 2, nullptr) == pdPASS;
  if (!valid) {
    if (clicks) { vQueueDelete(clicks); clicks = nullptr; }
    if (enabled) i2s_channel_disable(channel);
    i2s_del_channel(channel);
    channel = nullptr;
    return false;
  }
  ready = true;
  digitalWrite(AMPLIFIER_PIN, initiallyMuted ? HIGH : LOW);
  return true;
}

void buttonAudioMute(bool value)
{
  muted.store(value);
  if (clicks) xQueueReset(clicks);
  if (ready) codecWrite(0x31, value ? 0x60 : 0x00);
  if (ready) digitalWrite(AMPLIFIER_PIN, value ? HIGH : LOW);
}

void buttonAudioPlay()
{
  if (!ready || muted.load() || previewMuted.load()) return;
  uint8_t click = 1;
  xQueueOverwrite(clicks, &click);
}

void buttonAudioVoice(bool enabled)
{
  voiceEnabled.store(enabled);
  if (!enabled && clicks) xQueueReset(clicks);
}

bool buttonAudioVoiceEnabled() { return voiceEnabled.load(); }

void buttonAudioSpeak(PetVoice phrase)
{
  if (!ready || muted.load() || previewMuted.load() || !voiceEnabled.load() || !volume.load()) return;
  uint8_t message = uint8_t(phrase) + 2;
  xQueueOverwrite(clicks, &message);
}

bool buttonAudioReady() { return ready; }
bool buttonAudioMuted() { return muted.load(); }
void buttonAudioSetVolume(uint8_t value) { volume.store(min(uint8_t(100), value)); }
uint8_t buttonAudioVolume() { return volume.load(); }

void buttonAudioReport()
{
  Serial.printf("{\"event\":\"audio\",\"ready\":%s,\"muted\":%s,\"volume\":%u,\"voice\":%s,\"write_result\":%d,\"write_bytes\":%u}\n",
                ready ? "true" : "false", muted.load() ? "true" : "false", volume.load(), voiceEnabled.load() ? "true" : "false",
                lastWriteResult.load(), lastWriteBytes.load());
}

void buttonAudioPreviewMute(bool enabled)
{
  previewMuted.store(enabled);
  if (enabled && clicks) xQueueReset(clicks);
}
