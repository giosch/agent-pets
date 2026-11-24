# Agent Pets Habitat on your desktop

Agent Pets runs under your own account. The installer bundles the Python runtime, artwork, and browser application. Claude Code and Codex each use their existing local installation and user profile.

## Install and see your first pet

Look for a release tagged `desktop-v` in [this fork’s releases](https://github.com/giosch/agent-pets/releases). Until one is published for your platform, the [checkout instructions](../README.md#browser-habitat) are available. Untagged workflow artifacts are development builds. Windows Application Control can block unsigned development builds.

| Platform | Package and entry point | Installed command |
|---|---|---|
| Windows x64 | Run the Setup EXE, then open **Agent Pets Habitat** from Start. | `%LOCALAPPDATA%\Programs\AgentPetsHabitat\agent-pets.exe` |
| macOS, Apple silicon or Intel | Mount the DMG for your architecture and open **Install Agent Pets**. Open the installed app from your user Applications folder. | `~/Library/Application Support/AgentPetsDesktop/agent-pets` |
| Linux x86-64 | Run `sh ./Agent-Pets-<version>-linux-x86_64.run`, then open **Agent Pets Habitat** in your desktop application menu. | `$XDG_DATA_HOME/agent-pets-desktop/agent-pets`, normally under `~/.local/share` |

1. On first launch, open **Connections** and connect Claude Code, Codex, or both. The app lists the profile it configured for each agent. Existing checkout hooks in those profiles are migrated. Other tools’ hooks are preserved.
2. Select **Check command** to verify that the registered command reaches the host. In Codex, review changed hooks when prompted. The habitat can read reported trust status. Trust decisions belong to you in the coding client.
3. Send a prompt in a local chat. Connections shows the most recent real activity and its time. A successful connection check alone leaves the habitat empty. Select **Open habitat** to see the pet.
4. Enable **Start when I sign in** if you want the host available automatically. It uses your Windows Run entry, macOS LaunchAgent, or Linux desktop autostart entry. Opening the application again uses the same host. Closing a tab leaves the host running.

## Diagnose or recover

Open the app from your application menu to manage the host. A separately opened localhost URL can display the scene. Use the **Live** link to return to Connections. If a hook needs repair, select **Repair** for that agent, check the command again, then send a real prompt. If the host fails to start, look at `~/.agent-pets/habitat/host.log` (under your user folder on Windows). A checkout host that the installer cannot identify may need to be closed manually before migration.

**Check for updates** looks for a newer compatible desktop package in this fork. Download and run that installer. The installer verifies the staged files and tests the runtime before switching releases. To switch back after an upgrade, run the installed command in the table above with the argument `rollback-desktop`. On Windows PowerShell, for example:

```powershell
& "$env:LOCALAPPDATA\Programs\AgentPetsHabitat\agent-pets.exe" rollback-desktop
```

Rollback requires an earlier installed version. It verifies that version again and restarts the host if it was running. Reopen the application to manage the restarted host. Session data, installed artwork, and hook paths are shared across these releases.

Use **Uninstall Agent Pets** in Connections, or uninstall from Windows Installed Apps. Uninstall removes the application's hooks, shortcuts, and sign-in registration. Keeping saved sessions and installed artwork is the default. Choose the erase option to remove those as well. Browser-local preferences are managed by the browser.

## Build and release

On each native build platform, install `desktop/requirements-build.txt` into a Python build environment and run `python desktop/build.py --out installers --version 0.1.0` from the repository root. The release workflow also builds an earlier version, checks out the pinned original host, and runs `desktop/test_install.py` against both packages on disposable CI accounts. That test changes real per-user desktop registrations on its runner.

The [release workflow](../.github/workflows/desktop-habitat.yml) defines the signing secret names. Tagged release jobs need an authorized Windows Authenticode identity and an Apple Developer ID identity with notarization credentials. Only after the native package jobs pass does the publish job attest the artifacts and create the GitHub release. Test the signed artifacts under the target machine’s actual policy, then connect both real clients and observe an event from each before declaring a desktop release ready.
