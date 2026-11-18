"""Per-user desktop launch, connection checks and login registration."""
import http.client
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import webbrowser

from .hooks import _our_hook, config_path, expected_handler, launch_command
from .adapters import HOOKS


def control(directory, action):
    try:
        info = json.loads((directory / "connection.json").read_text(encoding="utf-8"))
        conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=2)
        try:
            conn.request("POST", "/internal/" + action, b"", {"Authorization": "Bearer " + info["key"]})
            response = conn.getresponse()
            if response.status == 200 and json.loads(response.read()).get("app") == "clawd-tank":
                return info
            if action == "stop" and response.status == 204:
                return info
        finally:
            conn.close()
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        pass
    return None


def launch(directory, background=False):
    info = control(directory, "ping")
    if not info:
        directory.mkdir(parents=True, exist_ok=True)
        cmd = [*launch_command(), "--state-dir", str(directory), "serve"]
        opts = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        with (directory / "host.log").open("ab") as log:
            child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **opts)
        for _ in range(100):
            info = control(directory, "ping")
            if info:
                break
            time.sleep(.1)
        if not info:
            raise RuntimeError(f"Could not start the habitat. See {directory / 'host.log'}")
    if not background:
        page = "" if (directory / "setup-complete").exists() else "connections"
        webbrowser.open(f"http://127.0.0.1:{info['port']}/{page}#manage={info['management']}")
    return info


def integration(source, directory):
    path = config_path(source)
    expected = expected_handler(source, directory)
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        groups = settings.get("hooks", {})
        found = []
        for event in HOOKS[source]:
            handlers = [h for g in groups.get(event, []) for h in g.get("hooks", []) if _our_hook(h, source)]
            found.append(handlers)
        if all(items == [expected] for items in found):
            state = "installed"
        else:
            state = "repair" if any(found) else "available"
    except (ValueError, AttributeError, TypeError, OSError):
        state = "invalid"
    return {"state": state, "profile": str(path)}


def probe(source, directory):
    if integration(source, directory)["state"] != "installed":
        return False
    import secrets
    token = secrets.token_hex(16)
    handler = expected_handler(source, directory)
    if source == "claude":
        argv = [handler["command"], *handler["args"]]
    elif os.name == "nt":
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", handler["commandWindows"]]
    else:
        argv = ["/bin/sh", "-c", handler["command"]]
    try:
        result = subprocess.run(argv, input=json.dumps({"habitat_check":token}).encode(), capture_output=True,
                                timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode == 0 and token.encode() in result.stderr.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return False


def codex_trust(directory):
    """Ask the local runtime about these handlers. No trust decisions are written."""
    exe = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if not exe and sys.platform == "darwin":
        for app in (Path("/Applications"), Path.home()/"Applications"):
            candidate = app / "Codex.app/Contents/Resources/codex"
            if candidate.is_file():
                exe = str(candidate)
                break
    if not exe and os.name == "nt":
        try:
            result = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
                                     "(Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1).InstallLocation"],
                                    capture_output=True, text=True, timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
            location = result.stdout.strip()
            if location:
                candidate = Path(location)/"app/resources/codex.exe"
                if candidate.is_file():
                    exe = str(candidate)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not exe:
        return "unknown"
    handler = expected_handler("codex", directory)
    command = handler.get("commandWindows",handler["command"])
    msgs = [{"method":"initialize","id":1,"params":{"clientInfo":{"name":"habitat","version":"1"},
             "capabilities":{"experimentalApi":True}}}, {"method":"initialized","params":{}},
            {"method":"hooks/list","id":2,"params":{"cwds":[str(Path.home())]}}]
    try:
        # Keep stdin open until hooks/list has replied. Some app-server versions
        # cancel pending RPCs immediately upon EOF.
        import threading
        found = []
        with subprocess.Popen([exe, "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
            def read():
                try:
                    for line in proc.stdout:
                        msg = json.loads(line)
                        if msg.get("id") == 2:
                            found.extend(h for row in msg.get("result", {}).get("data", []) for h in row["hooks"]
                                         if h.get("command") == command and
                                         Path(h.get("sourcePath") or "") == config_path("codex"))
                            break
                except (OSError, ValueError, KeyError):
                    pass
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                proc.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
                proc.stdin.flush()
                reader.join(4)
            finally:
                proc.kill()
                reader.join(1)
        if any(h.get("trustStatus") == "untrusted" for h in found):
            return "review"
        if any(h.get("enabled") is False for h in found):
            return "disabled"
        if len(found) == len(HOOKS["codex"]) and all(h.get("trustStatus") in {"trusted","managed"} for h in found):
            return "trusted"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "unknown"


def login(directory, enabled=None):
    argv = [*launch_command(), "--state-dir", str(directory), "launch", "--background"]
    if os.name == "nt":
        if getattr(sys, "frozen", False) and os.environ.get("CLAWD_TANK_LAUNCHER"):
            argv[0] = str(Path(argv[0]).with_name("clawd-tank-desktop.exe"))
        import winreg
        location = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = (winreg.OpenKey(winreg.HKEY_CURRENT_USER,location,0,winreg.KEY_READ)
                   if enabled is None else winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,location,0,
                                                              winreg.KEY_READ | winreg.KEY_SET_VALUE))
        except FileNotFoundError:
            return False
        with key:
            if enabled is True:
                winreg.SetValueEx(key, "ClawdTankHabitat", 0, winreg.REG_SZ, subprocess.list2cmdline(argv))
            elif enabled is False:
                try:
                    winreg.DeleteValue(key, "ClawdTankHabitat")
                except FileNotFoundError:
                    pass
            try:
                return bool(winreg.QueryValueEx(key, "ClawdTankHabitat")[0])
            except FileNotFoundError:
                return False
    if sys.platform == "darwin":
        path = Path.home() / "Library/LaunchAgents/io.clawdtank.habitat.plist"
        content = plistlib.dumps({"Label":"io.clawdtank.habitat", "ProgramArguments":argv, "RunAtLoad":True})
    else:
        path = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/clawd-tank-habitat.desktop"
        def quote(arg):
            for char in ('\\', '"', '`', '$'):
                arg = arg.replace(char, '\\' + char)
            return '"' + arg.replace('%','%%') + '"'
        content = ("[Desktop Entry]\nType=Application\nName=Clawd Tank\nExec=" +
                   " ".join(quote(arg) for arg in argv) + "\n").encode()
    if enabled is True:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    elif enabled is False:
        path.unlink(missing_ok=True)
    return path.exists()
