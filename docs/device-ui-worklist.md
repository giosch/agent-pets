# Agent Pets device UI worklist

Updated 2026-11-23. This file records the requested behavior and implementation/verification status.

## Verified baseline

- [x] ES3C35P landscape orientation and 180-degree placement.
- [x] Native browser artwork and scenery on the display, PSRAM sprite rendering.
- [x] Hidden controls revealed by touch, minimal persistent connection indicator.
- [x] Audio submenu with mute, logarithmic volume, and full digital range at 100%.
- [x] Paired vendor-defined HID, custom GATT fallback, separate PC/companion/backend connection states.
- [x] Stable pet ordering across turns; temporary unsaved Codex sampling forks excluded.
- [x] Local Claude background tasks stay active until actual completion; user verified behavior and animation.
- [x] Pets, helpers, departure animations and badges lowered together by 30 px; compiled, uploaded and framebuffer verified.

## Current request

- [x] Tap a pet to identify its actual session name and Claude/Codex source.
- [x] Show its current activity in a short, readable speech bubble.
- [x] Keep bubbles temporary; default habitat stays quiet and uncluttered.
- [x] Brief automatic bubbles for new approval/question/failure states, with a cooldown.
- [x] Preserve settings access and pet hit targets with controls hidden.
- [x] Verify title lookup and bounded display packets (193 portable tests), plus real Codex/Claude bubble and Audio settings framebuffer captures.
- [x] User confirmed physical pet taps show the correct session names and spoken audio works.
- [x] Spoken audio: requested, not deferred away. Add an opt-in Voice setting in the Audio submenu, honoring master mute and volume. Use short status phrases rather than reading conversation text.
- [x] User confirmed spoken voice quality on the real speaker. Speech shares the existing mute/volume path; event cooldown and saved Voice settings are implemented.

## Original repository ideas evaluated

The original firmware displays project names and short notification messages, briefly expands new alerts (2.5 s), then uses compact cards and a waiting count. It also has a clock. For this habitat, use on-demand session identification and occasional actionable speech bubbles; avoid a permanent notification list or scrolling text over the scenery. Spoken audio is an optional supplement.

## Scope decisions

- Remote/cloud Claude integration is explicitly out of scope at the user's request.
- An idle but still-running local Claude chat remains a separate session/pet; the older Test chat explained the third pet.
- No spoken audio is considered complete until implemented and tested; task completion reports must distinguish uploaded features from pending items.

## Additional quiet uses for the sky

- [x] Show elapsed time and active tool/helper counts only while a pet is selected.
- [x] A small PC-local clock alongside the revealed controls, following the original clock feature.
- [x] A brief connection/recovery card only when the user taps the connection indicator.
- [x] Progress counts only from successful Codex update_plan or local Claude TaskList results; no invented percentages or ETAs.

## Implementation notes

- Session names come from the local Codex title index and Claude native session metadata, never from prompt/transcript text.
- Display metadata is bounded for the existing 4096-byte record protocol.
- Voice uses five short offline-generated phrases and about 26 KB of IMA ADPCM data; its saved setting defaults off.
- Automated portable checks currently pass: 193 tests. Firmware compiled and uploaded successfully; flash hashes verified. Real Codex/Claude title bubbles and the Audio submenu are visually verified. User confirmed that Voice and session names work on the device.

## Latest uploaded build

- Flash use: 3,144,195 / 3,145,728 bytes; globals 64,208 bytes.
- Firmware upload to COM5 completed with verified flash hashes.
- Paired HID reconnected after the upload (GATT recovery also worked).
- Five spoken phrases: approval, question, attention needed, ready, working. Voice off by default, saved across restarts when changed.
- Original permanent notification cards were adapted into transient pet bubbles. The clock is visible with controls; selected-pet details show observed activity age, active tools/helpers, and genuine reported plan/task counts when available.

User acceptance: "Voice and session names work." The requested tap-to-identify, transient bubbles and optional spoken audio are implemented, uploaded and accepted. The additional quiet sky-space features are implemented without adding permanent text to the default scene.

## Adaptive bubble typography

- [x] Size the session title and status to the largest measured font that fits, with word wrapping, preserved margins and no overlap.
- [x] Use the additional sky height while controls are hidden; preserve HUD clearance when controls are visible.
- [x] Compile, upload and visually check short and long real session titles.

## Approval-state correction

- [x] Distinguish a pending Codex permission request from a native Windows command proven to have started. Match a SHA-256 command fingerprint, the native agent parent PID and its creation identity, and a newer child-shell creation time. Clear only the uniquely matched call; preserve unknown, duplicate, stale, reused-PID and unrelated permission waits. No blind timeout. Permission and tool-start events may arrive in either order.
- Live verification: the real native command retained its active-call record for 24 observations; its permission cleared at second 3 while execution continued. Other platforms and unsupported tools retain the conservative hook-based permission behavior until completion.
- Autonomous Codex goal turns without UserPromptSubmit now advance using newer UUIDv7 turn identity, preserving pet identity while rejecting stale turns.
- The lever/button held back by the tail plus the lock badge is the correct approval artwork.

Adaptive typography verified on the flashed board: large short Test title, longer Codex session title, balanced two-line wrapping, readable status text, hidden controls and visible controls. Side padding remains 14 px, vertical padding 8 px, and the font scale resets before other UI rendering. HID reconnected after the hash-verified upload.


## Independent verification, 2026-11-23

- 193 portable tests cover execution/approval correlation, both permission/tool-start orders, independent waits, native process identity, autonomous turns, actual plan/task counts, activity timing, bounded packets, HID/GATT framing, title lookup and local Claude background activity.
- COM5 upload verified the firmware flash hash; paired HID recovered without re-pairing.
- Real framebuffer captures verify the PC clock, selected-pet detail header, adaptive title typography, connection details, and the default hidden controls. Stopping the host and then the bridge produced distinct Waiting for habitat / Waiting for companion cards; both recovered over HID without re-pairing.
- Final live audit found no pending permission waits. An older pre-update diagnostic was cleared by collecting its successful native completion, without editing session state or expiring a permission by timeout.
- Speaker output was temporarily suppressed through a RAM-only diagnostic switch during overnight testing. Saved Voice, mute and volume preferences were preserved.
- No remote Claude integration or synthetic live sessions were added. Unrelated historical TODO.md tasks remain outside this device UI worklist.


## Power-saving follow-up, 2026-11-24

- [x] Research board/chip options and wake limitations; record evidence and implementation priorities in es3c35p-power.md.
- [x] Add saved brightness in Settings → Display, live dragging, bounded 1–100%, one preference write on release. Firmware compiled and uploaded with verified hashes. Restart persistence checked; user confirmed the physical slider works.
- Superseded by the implemented Eco/sleep behavior below, requested by the user after the research.


## Eco, idle screen-off and manual deep sleep

- [x] Eco default: reduced CPU/rendering load, coalesced PC traffic and automatic idle audio hardware suspension.
- [x] Saved timeout choices 1/5/15/30 minutes/Never, default five minutes.
- [x] Strong warning dimming (one tenth of the configured backlight level), no warning message, ten seconds before connected screen-off.
- [x] Wake gestures are consumed until finger release, preserving hidden controls.
- [x] Meaningful PC activity wakes/resets idle, including hidden sessions; routine snapshots, clocks and heartbeats do not.
- [x] Manual deep sleep from Settings or the BOOT Power menu, with explicit confirmation, persistent bonds/preferences, GPIO0 BOOT wake, safe output holds and ordinary LCD sleep; user verified BOOT wake from real deep sleep.
- [x] 194 host tests plus compile-time policy checks; real telemetry verified connected screen-off, stopped drawing, parked audio, PC wake and timer-based deep-sleep reboot/reconnection.
- User acceptance: dimming tap only wakes; BOOT wakes connected screen-off and deep sleep.
- Connected screen-off was refined after the user found LCD SLPIN disables touch reporting: keep LCD/touch awake, with backlight/drawing/audio off.
- [x] User confirmed dark-screen touch wake and BOOT behavior work after the LCD/touch correction.
- User requested restoring five minutes after the short test and substantially stronger dimming; warning now fades to 10% of the selected brightness.
- Power consumption has not been measured; no percentage or battery-life claim is made.


2026-11-24: rotated the current landscape placement another 180 degrees at the user’s request, with the matching inverse touch transform.


## Battery and BOOT hold follow-up

- [x] Added a conditional battery icon, estimated percentage and measured voltage, with saved Installed configuration. Empty connector was measured at approximately 4.11 V while the user confirmed no pack was attached; automatic voltage-only presence detection would be misleading.
- [x] Added a 1.2-second BOOT hold Power menu with explicit Deep sleep and Cancel choices; preserve short-press wake/reveal and suppress short-release after long press.
- Firmware built and uploaded to COM5 with verified flash hashes. Flash: 3,144,195 / 3,145,728 bytes; globals: 64,208 bytes. Compile-time battery-curve and BOOT gesture checks pass; all three HID security guards pass.
- Real framebuffer captures verified the disabled battery page, enabled indicator and voltage page, minimal ambient indicator and BOOT Power menu. Installed was restored off for the user’s empty connector. Preview used actual charger voltage, not a real-cell capacity test.
- [x] User confirmed the uploaded battery/BOOT menu updates work great on 2026-11-24. No real-cell capacity calibration is possible until a battery is fitted.
