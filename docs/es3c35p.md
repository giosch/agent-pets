# LCDWIKI ES3C35P hardware baseline

The hardware baseline for the Agent Pets habitat is the LCDWIKI ES3C35P. It has an ESP32-S3, a 3.5-inch 320×480 ST77922 QSPI touchscreen, 16 MB of flash, and 8 MB of OPI PSRAM. The Arduino finger-paint sketch is the reference for display output and touch input.

## Tested Windows setup

The sketch uses Arduino IDE 2.3.11, Arduino CLI 1.6.0, Espressif Arduino-ESP32 3.3.13, and LovyanGFX 1.3.0. The ES3C35P display and touch driver is version 1.0.1, pinned to commit `64a7cfb496bfa9417c22d361e50c853d4dc21d2f`. [Pinned board driver](https://github.com/JasonBolbach/ES3C35P/blob/64a7cfb496bfa9417c22d361e50c853d4dc21d2f/src/LGFX_ES3C35P.hpp)

In the Windows sketchbook at `%USERPROFILE%\Documents\Arduino`, the reference is `ES3C35P_FingerPaint\ES3C35P_FingerPaint.ino`. Its sibling `sketch.yaml` selects the board for the CLI. The installed driver header is `libraries\ES3C35P\src\LGFX_ES3C35P.hpp`.

| Board setting | Tested value |
| --- | --- |
| Board | ESP32S3 Dev Module |
| CPU frequency | 240 MHz |
| Flash mode | QIO 80 MHz |
| Flash size | 16 MB |
| PSRAM | OPI PSRAM |
| Partition scheme | 16M Flash (3MB APP/9.9MB FATFS) |
| USB mode | Hardware CDC and JTAG |
| USB CDC on boot | Enabled |
| Upload mode | UART0 / Hardware CDC |
| Upload speed | 921600 |

New ES3C35P sketches can reuse the reference `sketch.yaml` verbatim.

```yaml
default_fqbn: esp32:esp32:esp32s3:FlashMode=qio,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,USBMode=hwcdc,CDCOnBoot=cdc,UploadMode=default
```

## HID connection, GATT fallback and settings

The device advertises as **Agent Pets XXXX**. Pair it through the computer's Bluetooth settings after choosing **Settings → Bluetooth → Pair PC** on the display. New pairings are accepted for two minutes; known bonded computers can reconnect afterward. Changing from the earlier GATT-only firmware adds a HID descriptor, so remove the previous device in the computer's Bluetooth settings, choose **Forget paired PCs** on the board (two taps), then pair again. This refreshes the OS's cached service table and report descriptor.

Install the companion's Bluetooth extra with `pip install ".[bluetooth]"`, then run the live habitat and `python host/habitat.py bluetooth-display`. The default `--transport auto` prefers HID and retains the custom GATT connection as fallback. Use `--transport hid` or `--transport gatt` to diagnose either path. Stop `serial-display` when switching to wireless. USB may continue supplying power. The firmware uses NimBLE-Arduino **2.5.2**; the companion uses HIDAPI's Python binding **0.15.0** and Bleak **3.1.0**.

The upper-right gear opens Audio and Bluetooth settings. Audio retains the saved mute switch, logarithmic volume slider and Test sound control. Bluetooth shows the device name, pairing window and bond/connection state. The expanded habitat status says **HID**, **GATT**, **USB**, Demo or Offline. Settings stay open until closed. Habitat controls still hide after eight seconds, leaving the small ambient connection mark visible.

### Native HID transport

The BLE HID service (`0x1812`) exposes one vendor-defined application collection, usage page `0xFF00`, usage `1`, with Generic HID appearance `0x03C0`. It declares no keyboard, mouse or media-key inputs. The development PnP identity is VID `0x303A`, PID `0xA937`, version `0x0100`. The companion verifies a protocol capability report before sending snapshots, independently of those identifiers.

| Report | Direction | Payload |
| --- | --- | --- |
| Input 1 | Board → PC | 8-byte application acknowledgement |
| Output 1 | PC → board | 63-byte snapshot fragment |
| Feature 2 | Board → PC | 63-byte capability/status report, 16 meaningful bytes |
| Feature 3 | PC → board | 63-byte snapshot fragment via acknowledged Set_Report |

HIDAPI buffers include a leading report-ID byte, making data reports 64 bytes on the PC. A fragment contains magic `0xC1`, flags (bit 0 start, bit 1 end), uint32 little-endian transaction ID, uint16 little-endian byte offset, uint8 payload length and up to 54 JSON bytes, with zero padding. The JSON has the same version-1 snapshot structure as GATT and includes `tx`; its transaction ID must match the fragment envelope. The maximum assembled JSON is 4095 bytes. Missing, out-of-order, oversized or stale fragments discard the incomplete assembly. The two transports have separate assembly buffers and share one validated scene receiver.

Input acknowledgement bytes are `0xC1`, result (0 applied, 1 rejected), uint32 little-endian `tx`, protocol version 1 and a reserved zero byte. Capability Feature 2 starts with `APH1`, protocol 1, report size 63 and uint16 maximum record size 4096, followed by the last result and uint32 transaction, transport marker and zero padding. The companion accepts HIDAPI responses with or without the report-ID prefix.

The companion sends through Feature 3 using `send_feature_report`, which provides acknowledged HID Set_Report writes. This avoids known Windows BLE `hid_write` cases where an unacknowledged Output report can be silently dropped. It waits for a matching Input acknowledgement, with Feature 2 status polling as recovery if the notification is lost. An OS write success alone does not acknowledge a scene. [HIDAPI Windows behavior](https://github.com/libusb/hidapi/wiki/Known-Issues)

HID is enumerated through each OS's native driver. `--serial` selects one board when several HID endpoints match. Windows and macOS use the `hid` Python module; Linux uses its Bluetooth-capable `hidraw` module. Linux desktop users can install `host/agent_pets_habitat/install_resources/70-agent-pets-hid.rules` into `/etc/udev/rules.d/`, reload udev rules and reconnect the board to grant the active user access. Bluetooth devices are attached through `uhid`, so USB-only VID/PID permission rules do not match. [HIDAPI backend documentation](https://github.com/libusb/hidapi)

### Automatic fallback and recovery

The bridge falls back to GATT if HID is absent, denied, incompatible or stops acknowledging snapshots. It periodically checks whether a usable HID endpoint has become available and switches only after the capability handshake succeeds. Each connection and transport switch starts a fresh habitat event stream, sends a complete current snapshot and restores subscriptions. The protocol retains transaction IDs and acknowledgements so incomplete or stale traffic cannot acknowledge a later scene.

Windows GATT discovery enumerates the OS's already-paired BLE endpoints. Linux does the same through BlueZ's `Device1.Paired` property. The saved address in `bluetooth-display.json` is a selection hint; it cannot authorize a device absent from the OS pairing list. `--address` selects a specific GATT fallback endpoint. macOS uses CoreBluetooth discovery by service UUID, and the OS may present its native pairing prompt when an encrypted characteristic is first accessed. macOS uses peripheral UUIDs rather than Bluetooth MAC addresses. [Bleak macOS behavior](https://bleak.readthedocs.io/en/latest/backends/macos.html#pairing)

The fallback GATT service remains `96a5d701-e7c7-4b8f-9df4-23dd0f624a01`; RX uses `d702` and TX uses `d703`. RX accepts encrypted newline-delimited snapshots up to 4096 bytes including the newline. TX returns result byte plus uint32 little-endian transaction ID. The companion respects MTU-3 and caps writes at 244 bytes. Bonding uses encrypted BLE Secure Connections and the explicit Pair PC window. **Forget paired PCs** erases board bonds; also remove the pairing in OS settings before enrolling again. Audio and artwork preferences remain saved.

The firmware retains the original 3 MB app partition, landscape orientation, PSRAM sprite renderer and audio gain curve. Windows hardware verification is performed on the connected ES3C35P. Mac and Linux have platform adapters and protocol coverage but still require testing on those physical hosts.

### Connection states

The computer link, companion and habitat backend are tracked independently. The display distinguishes **PC disconnected** (Bluetooth link absent), **Companion offline** (computer connected but no recent companion traffic), **Backend not found** (companion reachable but no usable backend stream), and live **HID/GATT/USB**. The Bluetooth settings page gives the matching recovery instruction. The unobtrusive ambient mark uses a grey slash for no PC, amber pause bars for a missing companion, an amber square for a missing backend, and a green dot for live state. Demo retains its separate play symbol.

The companion sends version-1 `bridge_status` records with a boolean `backend` field every second and immediately on backend availability changes. They use the same transaction framing and acknowledgements as snapshots. Valid snapshots also prove companion activity. Companion traffic expires after 3.5 seconds; snapshots expire after five seconds. A new Bluetooth connection generation invalidates old activity, and recovering backend status alone cannot revive stale pet badges before a new valid snapshot. Empty live habitats remain live; no synthetic sessions are sent to represent connection state.

### HID input capability boundary

This firmware's HID descriptor declares only vendor usage page `0xFF00`, application usage `1`. It declares no keyboard, mouse, consumer/media or system-control collection and no keyboard boot reports. Its Input report carries eight bytes of acknowledgement data; the OS interprets that report as vendor application data. The companion decodes acknowledgement/status records and contains no keystroke or pointer injection mapping. Native USB uses hardware Serial/JTAG CDC, with no USB HID interface.

The actual paired Windows descriptor was read through HIDAPI and checked against the source descriptor. Regression tests reject standard HID usage pages, changed report layouts, keyboard boot reports and USB HID includes in this firmware. These properties apply to the installed firmware; replacing it with different firmware could change the device's declared capabilities.

### Verified on the Windows board

HIDAPI enumerates the vendor-only endpoint and sends acknowledged live habitat snapshots. The 4095-byte maximum JSON record succeeds. Out-of-order fragments and mismatched envelope/JSON transactions are rejected, and a fresh snapshot restores normal operation. The custom GATT fallback also carries acknowledged live state. Rebooting the board retained its OS pairing; the bridge recovered through GATT and then returned to HID automatically. The two settings pages and the live HID indicator were inspected from device framebuffer captures. The distinct Companion offline and Backend not found screens were exercised on hardware, including stale-badge suppression, then live operation was restored. The actual paired HID descriptor was read back and confirmed to contain only the vendor collection and expected data reports.

The firmware uses 3,075,163 bytes in the existing 3 MB app partition. The renamed portable host test selection passes 168 tests. Legacy macOS daemon and Unix-only socket tests cannot be exercised on this Windows machine. Mac and Linux hardware acceptance remains outstanding.

## Display and touch

At rotation `0`, the screen is 320 pixels wide and 480 pixels tall. The ST77922 writes pairs of columns, so a panel write must start at an even x coordinate and have an even width.

1. Initialize the display with `lcd.init()` and `lcd.setRotation(0)`.
2. Use an `LGFX_Sprite canvas(&lcd)`. Call `canvas.setPsram(true)` and `canvas.setColorDepth(16)`, then check that `canvas.createSprite(lcd.width(), lcd.height())` succeeds.
3. Draw into the sprite and send each changed frame with one `canvas.pushSprite(0, 0)`. The full-width transfer satisfies the alignment rule even for single-pixel lines and text.
4. Read touch coordinates with `lcd.getTouch(&x, &y)` in the same portrait orientation.

| Signal | ESP32-S3 GPIO |
| --- | --- |
| LCD CS / SCLK | 10 / 12 |
| LCD D0 / D1 / D2 / D3 | 11 / 13 / 14 / 9 |
| Backlight | 41 |
| Touch SDA / SCL | 38 / 39 |
| Touch reset / interrupt | 48 / 47 |

The touch controller uses I²C address `0x55`.

## Reproduce the finger-paint check

In PowerShell, list the ports after connecting the board. The verified native USB Serial/JTAG connection used `COM5`.

```powershell
$cli = Join-Path $env:USERPROFILE 'AppData\Local\Microsoft\WinGet\Packages\ArduinoSA.IDE.stable_Microsoft.Winget.Source_8wekyb3d8bbwe\resources\app\lib\backend\resources\arduino-cli.exe'
$config = Join-Path $env:USERPROFILE '.arduinoIDE\arduino-cli.yaml'
$sketch = Join-Path $env:USERPROFILE 'Documents\Arduino\ES3C35P_FingerPaint'
& $cli board list --config-file $config --no-color
```

Set `$port` to the port shown for the board, then build and upload the reference sketch using its saved settings. The verified upload from Codex used escalated access to the Windows Arduino directories and the USB port.

```powershell
$port = 'COM5'
& $cli compile --upload --port $port --jobs 8 --config-file $config $sketch --no-color
```

The reference upload verified the flash hashes. At 115200 baud, the sketch printed `LCD 320x480 up, touch configured`. On the physical screen, dragging drew a line, tapping a different swatch changed the drawing color, and **CLEAR** erased the drawing.

## Agent Pets pet firmware

The Arduino sketch in `firmware/AgentPets_ES3C35P` implements the browser habitat as a native landscape renderer at 480×320. Up to three pets share the selected scenery, with the browser's attention symbols, stable session palettes, helper companions, priority ordering, and overflow indicator. Clawd, Patch Fox, and Monke use artwork exported from the browser SVG packs. Tidepool and Pine Grove provide the scenery.

The device runs its own animation timelines, arrival and departure movements, brief reactions, and idle play. Rendering uses a landscape PSRAM sprite and a cached background. The completed frame is rotated into a full-screen 320×480 output sprite, keeping the panel at its tested hardware rotation `0`. Touch coordinates receive the inverse transform. The USB bridge sends session state and events to the device. Tap the left footer area to cycle characters, the middle to cycle scenery, and the right to toggle the local demo. Character and scenery choices persist in device storage.

The controls use a warm cream and forest-green theme, with raised buttons, selected-mode styling, and press feedback. The upper-right gear opens Settings with Audio and Bluetooth tabs. Audio has a mute switch, a 0–100% volume slider, and a Test sound button. Volume and mute settings persist across restarts. Button taps play a soft 60 ms tone. Sound starts enabled at 40% on a fresh installation. The slider uses a −70 to 0 dBFS curve, with zero volume fully silent. The enveloped note is normalized so 100% reaches the full-scale 16-bit peak of 32767, while lower settings retain fine control over quiet output. Muting silences the codec and puts the amplifier in standby, and unmuting plays a confirmation tone. During normal playback, the amplifier stays awake and I²S transmits silence between button sounds to avoid repeated standby pops. The audio worker runs separately from display rendering.

Controls start hidden. Tap anywhere to reveal them, then tap the desired control. A tap on the scenery dismisses the controls, and eight seconds without touch hides them automatically. Touching or dragging a control keeps the interface visible. A small connection mark blends into the scenery while controls are hidden. Its green dot indicates a live connection, an amber slash indicates offline, and an amber play symbol identifies the local demo.

### Audio hardware

The ES8311 codec uses I²C address `0x18` on the shared touch bus, GPIO38/39. The I²S output uses MCLK on GPIO17, BCLK on GPIO18, WS on GPIO21, and data out on GPIO15. GPIO1 enables the speaker amplifier at a low level. Codec initialization uses 24 kHz stereo 16-bit I²S with a 256× master clock and configures analog bias and reference power before enabling output. A connected speaker is required for audible feedback. [Board pin reference](https://github.com/78/xiaozhi-esp32/blob/main/main/boards/lcdwiki-es3c35p/config.h) · [Espressif ES8311 initialization reference](https://github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es8311/es8311.c)

The codec shares LovyanGFX's I²C bus locking with touch. When audio initialization fails, the Audio settings page reports that audio is unavailable.

The DAC volume register `0x32` is held at `0xBF` for 0 dB gain. `0xFF` adds 32 dB and makes short button tones excessively loud. The user slider attenuates the generated PCM signal. The board-specific audio example uses the same 0 dB ceiling and keeps the amplifier enabled during playback. [ES3C35P audio example](https://github.com/phirzcol/esp-s35/blob/main/main/AudioHAL.cpp) · [ES8311 register reference](https://files.waveshare.com/wiki/common/ES8311.DS.pdf)

To build and upload from the repository root, set `$cli` and `$config` using the PowerShell block above, confirm the port, then run the following command.

```powershell
& $cli compile --upload --port COM5 --jobs 8 --config-file $config '.\firmware\AgentPets_ES3C35P' --no-color
```

The host bridge requires pyserial. For a checkout, create an environment and install the USB extra from the repository root.

```powershell
python -m venv .debug\usb-venv
& .\.debug\usb-venv\Scripts\python.exe -m pip install -e '.[usb]'
```

Register checkout hooks for both agents with this persistent environment using `& .\.debug\usb-venv\Scripts\python.exe host\habitat.py install-hooks both`. Review changed hooks in Codex Settings → Hooks. This keeps the hook interpreter independent of the Codex app's versioned runtime packages.

Start the habitat host using your usual launcher or `python host/habitat.py serve`. In another terminal, run the bridge from the checkout.

```powershell
& .\.debug\usb-venv\Scripts\python.exe host\habitat.py serial-display --port COM5
```

The bridge discovers the running host through its state directory's `connection.json`. Supply the global `--state-dir` option before `serial-display` for a custom directory. A packaged installation with the USB extra also exposes `agent-pets serial-display --port COM5`.

To exercise four synthetic sessions, start `python host/habitat.py serve --demo --port 19874`, then pass `--url http://127.0.0.1:19874` to the bridge. The bridge promotes approvals, questions, and failures first, ready sessions second, and ordinary activity third, with arrival order breaking ties.

### Native artwork build

The generated `device_art.h` contains compressed RGB565 runs and animation timing. Regenerate it after editing the source artwork using Python with Pillow and Playwright installed. Chromium is used during the artwork build.

```powershell
python tools/export_device_art.py --browser 'C:\Program Files\Google\Chrome\Application\chrome.exe'
```

The exporter loads the built-in browser manifests and `assets/monke/production/monke.zip`. It samples CSS and SVG animation timelines at approximately 8 fps, deduplicates frames, and reserves three material colors for runtime palette substitution. The compiled artwork uses about 2.36 MB. New artwork is delivered by rebuilding and uploading the firmware.

### USB event binding

The bridge subscribes to `/v1/events`, restores the initial snapshot, and processes updates and removals. It sends a compact device snapshot about every 250 ms, with one newline terminating each record. The record carries `version: 1`, `type: "snapshot"`, `total` for the full session count, and `sessions` containing at most three selected records. Each session has `id`, `order`, `activity`, `attention`, `helpers`, and optional `active_calls`. A live reaction adds `moment` and `moment_token`. The device uses the token to play each reaction once. The maximum record length is 4096 bytes including the newline.

The device replaces its scene only after validating the whole record and replies with `{"event":"snapshot_applied"}`. Invalid or oversized records produce an error event and the parser resumes at the next newline. The bridge waits for acknowledgement and retries after a USB or host failure. Five seconds without a valid snapshot switches the screen to offline. A complete snapshot restores the scene after reconnect, including removal of sessions that closed during downtime.

The bridge suppresses stale reactions after reconnect. The touch demo stays selected until its footer control is tapped again. Close the bridge before uploading firmware or opening a serial monitor, since each uses the same USB port.

## Quiet pet bubbles and spoken status

Tap a pet directly, even with controls hidden, to show its current local chat title, Claude Code/Codex source and a short activity phrase for eight seconds. Tap the same pet or the bubble to dismiss it. Tapping empty scenery reveals the usual controls. Session titles come from local title indexes, refreshed every three seconds; they are added only to the paired display packet, not the public activity feed. If a title is unavailable, a stable source/session label is used.

New approval/question/failure states can show a four-second speech bubble at most once every 30 seconds. Existing alerts do not chatter on reconnect. Ordinary tool changes and turn completions do not automatically show text or speak.

Audio settings include a saved **Voice** toggle, off by default. When enabled, tapping a pet speaks a short status phrase; new actionable bubbles can speak too. **Test voice** plays a short phrase. Master Mute and the volume slider apply to speech and button sounds. Speech uses five offline Windows-generated phrases, IMA ADPCM at 12 kHz, decoded into the existing 24 kHz I2S stream; no cloud speech service or conversation text is involved. Rebuild audio assets with `tools/generate_device_voice.ps1` on Windows and then `python tools/export_device_voice.py`.

The USB diagnostic `{"type":"pet_info","index":0}` invokes the same real-pet inspection path as a tap; it does not inject or modify sessions.

Bubble typography measures each title and activity phrase, chooses the largest fitting sizes, and wraps/balances longer names. It keeps fixed margins, uses extra sky height with controls hidden, and preserves HUD clearance when controls are visible.


### On-demand activity and connection details

The selected-pet bubble header shows the observed activity's elapsed time and active tool count, with helper counts when present. Genuine completed/total step or task counts appear only after successful native Codex update_plan or local Claude TaskList results. Older sessions with unknown activity start times omit elapsed time. Offline bubbles show last-update age rather than stale active counts.

A PC-local HH:MM clock appears alongside revealed controls. Tap the persistent connection mark (or its expanded status pill) for an eight-second card identifying the PC link, companion/backend state, recovery hint and current USB/HID/GATT transport. Tap the card to dismiss it. The default habitat keeps only the small ambient mark.

For silent framebuffer checks, USB accepts `{"type":"preview_mute","enabled":true}`. This RAM-only override suppresses queued and playing device audio without changing saved mute, volume or Voice settings; send false to restore audio or reboot. `{"type":"connection_info"}` and `{"type":"pet_info","index":0}` exercise the same temporary cards as touch. These diagnostics do not create sessions.

The display snapshot additionally carries optional `local_time` (seconds since local midnight), per-session `elapsed` seconds, and `progress_done`, `progress_total`, `progress_kind` (`steps`/`tasks`). The same bounded and acknowledged 4096-byte framing applies.
