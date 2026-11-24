# ES3C35P power-saving research

Researched 2026-11-24 against the board schematic, primary chip documentation, the installed Arduino SDK and the actual Agent Pets firmware. Brightness and the subsequently requested Eco/idle-screen-off/manual-deep-sleep policy are now implemented; see the implementation status below. Current consumption has not been measured; chip figures are not whole-board figures.

## Existing firmware and SDK

- Backlight previously stayed at 200/255. Settings → Display now changes and saves it (1–100%, default approximately 78%).
- The renderer rotates and pushes a complete 480×320 frame every 60 ms, including static scenes. Touch is polled on each main-loop iteration, followed by delay(1).
- The ES8311 and I²S clocks remain enabled between sounds. Mute disables the speaker amplifier and digitally mutes the codec, but does not suspend the codec or stop I²S. Keeping the amplifier awake originally avoided repeated standby pops.
- BLE requests 15–30 ms connection intervals and zero peripheral latency. The companion regularly sends full snapshots, so reducing radio traffic is a separate host-side opportunity.
- The installed Arduino-ESP32 3.3.13 SDK has CONFIG_PM_ENABLE and CONFIG_BT_CTRL_MODEM_SLEEP disabled. Adding defines to the sketch does not rebuild those precompiled IDF components. Manual sleep and static CPU frequency changes are separate possibilities; connected automatic sleep needs a suitably configured SDK.

## Options, in implementation order

| Component | Change | Tradeoff / constraint |
|---|---|---|
| Backlight | Lower PWM brightness; later add idle dimming and complete backlight-off | Implemented manual slider. Largest likely immediate saving: vendor lists 120 mA backlight current, under its test conditions. |
| Rendering | Render on animation deadlines or visible changes; stop all drawing when dark | Keep active pets responsive. Static settings and empty habitats need fewer redraws. |
| Touch | Reduce polling frequency; use GPIO47 interrupt when appropriate | Keep the external touch controller scanning when touch wake is wanted. Verify IRQ behavior on hardware. |
| Audio | Shutdown amplifier on GPIO1, suspend ES8311, stop I²S/DMA and MCLK during longer idle periods | Follow the established analog power sequence on resume and test for pops and missed clicks. Shutting down the unused ADC path alone does not remove microphone supply power. |
| CPU | Benchmark 160 MHz, then 80 MHz with lower rendering load | Recheck QSPI, PSRAM, USB, touch and audio timing. A slower CPU is not automatically lower energy per rendered frame. |
| BLE | Longer connection intervals, peripheral latency, lower TX power, slower reconnect advertising | OS negotiates the final parameters; balance range/reconnect time and event latency. |
| Companion | Send changed state promptly, coalesce snapshots, use a sparse heartbeat while idle | Preserve acknowledgement/reconnect behavior and the device’s 3.5/5-second liveness windows. |
| LCD controller | Backlight off plus DISPOFF/SLPIN; resume with SLPOUT and redraw | Backlight-off alone leaves panel electronics running. Verify integrated touch keeps working in the chosen panel mode. |
| Other peripherals | Keep Wi-Fi/SD unused; explicitly send RGB LED black if needed | Do not initialize unused drivers merely to turn them off. Firmware cannot remove the standby supply current of every attached chip. |
| Flash/PSRAM | Stop transfers; use supported sleep/power-domain handling | Light sleep may retain RAM at a cost. Deep sleep restarts the application and rebuilds the display buffers. Avoid ad-hoc flash deep-power-down commands while executing code from flash. |

The vendor’s board current figures and wiring are documented on its [product page](https://www.lcdwiki.com/3.5inch_ESP32-S3_Display). A darker picture on this backlit IPS panel is not a substitute for lowering backlight PWM.

## Three useful operating modes

1. **Eco display:** keep pets and connection visible, lower brightness, avoid unnecessary rendering/audio clocks and reduce idle radio traffic.
2. **Connected screen-off:** turn off backlight, stop rendering, park audio, retain the BLE companion link. Touch, a local button or a meaningful PC event could restore the picture. This works first with the CPU awake; automatic CPU light sleep is a later SDK/driver optimization.
3. **Deep sleep:** shut down the display/audio as far as safely resumable, stop BLE, configure wake and enter esp_deep_sleep_start(). On wake the app boots, restores saved settings/bonds, rebuilds sprites, reconnects and receives a fresh session snapshot. The PC cannot directly wake the sleeping radio.

Do not enter explicit esp_light_sleep_start() while expecting BLE to stay connected. Use controller modem sleep and automatic light sleep for that design. See [Espressif sleep APIs](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/system/sleep_modes.html) and [power management](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/system/power_management.html).

## Wake on this board

| Wake source | Connected screen-off / CPU awake | Manual light sleep | Deep sleep |
|---|---|---|---|
| Screen touch, IRQ GPIO47 | Yes | GPIO wake is supported, provided touch remains active | No direct external wake: GPIO47 is outside RTC GPIO0–21 |
| BOOT button, GPIO0 | Yes | Yes | Supported candidate using RTC GPIO wake; configure pull-up and debounce/release handling |
| RTC timer | Software timer | Yes | Yes; scheduled wake reboots the application |
| BLE event | Yes | Only a supported controller-managed automatic-sleep design retains the link | No |
| RESET button | Reboots | Reboots | Reboots; also resets the panel |
| Native USB data | Yes | Not a reliable wake/recovery path in the current SDK | No; USB disconnects during deep sleep |

The screen is an external touch controller, not an ESP32 capacitive touch pad: enabling ESP32 touch-pad wake does not make GPIO47 a deep-sleep wake pin. A hardware change routing touch IRQ to a suitable free RTC pin could enable deep-sleep touch wake, but would still require keeping touch powered. The exposed GPIO45/46 expansion pins are not RTC wake pins either. Wiring and BOOT/RESET behavior are in the [board schematic](https://www.lcdwiki.com/res/ES3C35P/ESP32-S3%E5%8E%9F%E7%90%86%E5%9B%BE.pdf).

Native USB Serial/JTAG clocks stop in light sleep, and recovery may require reconnecting the cable. Deep sleep disconnects USB and normally enumerates it again on wake. USB power staying present does not itself constitute a wake source. See [USB Serial/JTAG sleep limitations](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-guides/usb-serial-jtag-console.html).

## Lowest-power limits and traps

The ESP32-S3 datasheet gives approximately 7–8 µA in deep sleep and 240 µA in a particular light-sleep configuration. These exclude this complete board; embedded PSRAM can add consumption. The ES3C35P also contains regulators, flash, LCD/touch, audio, microphone, RGB LED and charging circuitry. The schematic’s battery divider is 100 kΩ + 100 kΩ: with a 3.7 V battery it alone draws about 18.5 µA. Measure USB and battery operation separately, with charging excluded from idle measurements. See the [ESP32-S3 datasheet, current tables](https://documentation.espressif.com/esp32-s3_datasheet_en.pdf).

The ST77922 has ordinary sleep and a deeper standby command (0x4F). Deep standby requires a hardware RESX pulse to exit. This board shares LCD reset with ESP32 EN and the driver has no independent panel reset GPIO. Prefer ordinary SLPIN for a resumable first implementation; do not assume the panel can exit deep standby after a timer-only CPU wake. The chip also supports reduced panel refresh/limited-color modes, but those need panel-specific validation and can compromise the artwork. See the [ST77922 datasheet](https://dl.espressif.com/AE/esp-iot-solution/ST77922_SPEC_V0.1.pdf).

For audio, use the actual shutdown/resume sequence in [Espressif’s ES8311 codec driver](https://raw.githubusercontent.com/espressif/esp-adf/master/components/esp_codec_dev/device/es8311/es8311.c), rather than treating digital mute as hardware shutdown.

BLE sleep also needs an accurate clock. Do not assume a 32.768 kHz crystal is fitted or select the inaccurate slow RC clock for an established connection. Main-crystal sleep can remain useful but consumes more. Verify the options supported by our chosen IDF version. See [Espressif’s BLE low-power guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/low-power-mode/low-power-mode-ble.html).

## Bench plan before enabling sleep

Measure current for normal view, several brightness levels, backlight-off, audio suspended, display asleep, manual light sleep and deep sleep. Verify real touch wake, BOOT wake, timer wake, settings/bond retention, fresh session resynchronization and USB recovery. Hold backlight-off and amplifier shutdown safely through sleep; confirm they do not float back on. Keep a known-good firmware image for recovery. Whole-board sleep targets follow these measurements, not the bare-chip numbers.


## Implementation status after the user’s policy decision

Implemented in firmware and the companion: Eco default (160 MHz CPU, bounded redraw rate, audio clocks/codec parked between bursts), saved idle timeout, gentle warning dimming, connected screen-off, explicit Settings deep sleep and BOOT wake configuration. The companion coalesces identical snapshots and supplies a real-activity token so liveness traffic does not keep the screen awake. Selected brightness is preserved. Ordinary LCD sleep is used only in deep sleep; hardware-reset-only deep panel standby remains excluded. In connected screen-off, physical testing showed SLPIN disables touch reporting, so the LCD/touch controller now stays awake while backlight, rendering and audio are off.

An early deep-sleep test exposed NimBLE callback ownership during cleanup. Static server callbacks are now explicitly unowned, and sleep stops the stack without deleting the application objects immediately before RAM is discarded. Timer wake verified the real deep-sleep path and preference restoration. The user verified BOOT wake from connected screen-off and deep sleep, and wake-only taps during dimming. The user confirmed dark-screen touch wake and BOOT behavior after the SLPIN correction. Measured current remains a separate check recorded in the worklist. No CPU automatic light sleep, aggressive BLE interval/TX-power tuning, or hardware modifications are enabled.
