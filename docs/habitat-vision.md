# Pet habitat vision and requirements

The habitat is a companion for someone using local coding agents. A glance should tell them which sessions are active, what kind of work is underway, and whether one of the sessions needs them. A pet may do something playful between events. A question, approval, or failure that needs intervention takes precedence over play.

## What the fork starts with

Clawd Tank receives Claude Code hooks, tracks sessions and helpers in a Python daemon, and drives the Waveshare ESP32-C6-LCD-1.47 over BLE and an SDL simulator over TCP. Both use the same embedded scene code. The board has a clock, notification cards, a button, and an RGB LED. The daemon persists sessions and restores the scene when a connection returns. Its v2 messages name crab animations and select up to four pets by arrival order. The packaged menu bar application is for macOS. A contributor maintains a separate [Linux port](https://github.com/VloStudios/clawd-tank-linux).

The original SDL simulator documents a macOS build with Xcode, CMake, and SDL2. The new browser habitat is the software display for Windows, macOS, and Linux. Both can coexist in the same checkout. [Original simulator guide](../simulator/README.md)

## What the person sees

- Each open coding session has a pet with a stable identity. A modular palette lets sessions share a character design and still look different.
- The browser shows up to three pets. Outstanding questions, approvals, and failures requiring intervention get first choice of a slot. Finished turns come next, followed by ordinary activity. Arrival order breaks ties. An overflow symbol indicates other open sessions.
- A finished turn gets a brief celebration followed by a quiet ready symbol. Sending the next prompt or ending the session clears it on all displays. A display follows the coding session, including when the person switches tabs.
- The scene uses pet poses and symbols. Session titles, prompt text, tool content, and error messages belong in the coding client. Screen-reader descriptions and a symbol guide explain the visuals.
- A character and its habitat are independently selectable. Artists assign palette roles such as body, shadow, and accent once. A renderer can draw these at runtime or bake them into its own exported assets. A change of scenery preserves the pet’s identity.

## PC architecture

```text
Claude Code ─┐
             ├─ hook command → runtime adapter → loopback receiver → session state
Codex ───────┘                                                           │
                                              versioned snapshot + live updates
                                                                        │
                                                one or more display endpoints
```

The portable host uses Python 3.10+ and its standard library. Each runtime invokes a short command with a JSON hook on stdin. The adapter recognizes the runtime’s event names and forwards only identifiers and the normalized observation. One local host serializes concurrent changes and atomically saves session state. The read-only browser stream has no credentials for submitting observations. JavaScript renders activity, SVG provides the animation and scenery, and CSS lays out the habitat.

The Claude adapter reuses the existing hook normalizer. Both host implementations use the same atomic JSON writer. The original animated crab SVGs are the source art for the browser’s Clawd character. The browser has its own endpoint implementation and runs independently of the macOS launcher, SDL2, and the ESP32 toolchain.

Windows, macOS, and Linux run the same host and browser assets. OS-specific concerns in the browser milestone are hook command invocation, settings paths, and the host’s single-writer file lock. The supported agent surfaces are local Claude Code and local Codex sessions configured to run command hooks. The runtime controls when those hooks fire. An adapter can express generic activity when a tool or hosted operation supplies less detail. A retryable model attempt can produce a brief setback. An explicit terminal failure can request intervention.

## What each coding client can tell the pet

| Display information | Claude Code | Codex |
|---|---|---|
| Presence | Session start and end add or remove a pet. Subagent start and stop update its helper count. | The same lifecycle events map to the same session and helper behavior. |
| Current activity | `Read` and `Grep` mean inspecting. `Edit` and `Write` mean editing. | `apply_patch` also means editing. A supported shell hook for `git status` means inspecting. A prompt establishes generic working when a hosted tool supplies no detail. |
| Attention | A permission request raises the approval symbol. `AskUserQuestion` raises a question. `StopFailure` raises the intervention symbol. | Permission requests and user-input tools raise the corresponding symbols. Both runtimes mark a finished turn ready and clear it on the next prompt. |
| Brief events | A completed turn, reported tool failure, or compaction can produce a visible reaction. | A completed turn, reported MCP error, failed model attempt, compaction, or interruption can produce a reaction. |

Local Claude Code terminal sessions and local sessions in the desktop Code tab share hook settings. Local Codex terminal and desktop sessions can both run command hooks. The terminal offers `/hooks` for review and the desktop app offers Settings → Hooks. The command must execute on the same computer as the habitat host to reach its loopback address. Codex cloud orchestration has a different hook surface, and hosted tools such as web search provide no local tool-use detail. [Claude Code shared configuration](https://code.claude.com/docs/en/desktop#shared-configuration) · [Codex hook review and tool coverage](https://learn.chatgpt.com/docs/hooks)

## Delivery order and acceptance

The browser milestone includes everyday desktop installation. A person can install under their own account, choose either agent, observe a real chat, and reopen the same habitat from the application menu. Git and Python are build dependencies for contributors. The desktop package bundles the runtime for users.

Each installation has a stable hook command and a durable local activity inbox. A display reconnects from current state even if an agent closed during host downtime. The Connections page distinguishes registration, a synthetic command check, and the most recent real activity. Optional sign-in startup belongs to the host, so opening more display tabs never starts another host.

Desktop release acceptance covers migrating live checkout sessions, interrupted staging, upgrades, rollback, sign-in registration, and uninstall with retained or erased data. Exercise packaged builds on Windows, Ubuntu, and both Mac architectures, then verify a signed production install with real local agents. The [desktop guide](../desktop/README.md) covers installation and recovery.

1. **Local browser habitat.** Drive the browser with local Claude Code and Codex hooks, independent characters and scenery, persistent palette identities, and snapshot recovery. Test four sessions on three visible slots. Promote a hidden session that requests approval, complete a different turn, resume it, switch scenery, and reconnect a second tab. Exercise the installed commands and rendered scene on Windows, macOS, and Linux.
2. **Physical endpoints.** Bring the same activity vocabulary to the existing Waveshare board first. Validate BLE payload sizes, disconnect recovery, palette rendering, and memory on the physical device. Define and test transport-specific framing for BLE, TCP, and USB serial. Make a second board implementable from the protocol and fixtures. Each endpoint owns its rendering. Clock, brightness, LED, and button behavior are optional device features.
3. **Installable hardware artwork.** For hardware supporting custom art, export the character or habitat once per renderer and transfer the pack independently of live activity. The user must be able to replace artwork without rebuilding firmware. Test interrupted transfers and preserve the previous working pack. The browser export/install command and SVG pack format are the first working example.
4. **Android stretch goal, after working hardware.** Make an Android phone or tablet another pet display. Evaluate USB on a real PC–Android pair, including USB roles, permissions, reconnects, and how the host discovers the device. TCP or BLE can carry the same activity if they better suit the particular device. The choice of USB mode and the Android renderer belongs to that milestone.

## Agent references

The supported hook surface and trust review are maintained by the runtime vendors. See the [Claude Code hook reference](https://code.claude.com/docs/en/hooks) and [Codex hook reference](https://learn.chatgpt.com/docs/hooks).
