"""Install observational hooks and forward one hook's stdin to the local host."""
import http.client
import json
import os
from dataclasses import asdict
from pathlib import Path
import re
import shlex
import sqlite3
import sys

from clawd_tank_daemon.session_store import write_json_atomic
from .adapters import HOOKS, normalize

LAUNCHER = Path(__file__).resolve().parents[1] / "habitat.py"
STATUS = "Updating Clawd Tank habitat"


def _windows_command(argv: list[str]) -> str:
    # Codex may submit this same string to cmd.exe or PowerShell. A bare
    # executable works in both. Keep normal paths readable in hook review and
    # pass punctuation literally through both shells, including $ and %.
    def literal(arg):
        safe = re.sub(r"[^\w .:/\\-]", lambda m: f"' + [char]::ConvertFromUtf32({ord(m[0])}) + '", arg)
        return f"'{arg}'" if safe == arg else f"('{safe}')"

    command = " ".join(literal(arg) for arg in argv)
    return f'powershell.exe -NoProfile -NonInteractive -Command "& {command}"'


def config_path(source: str) -> Path:
    if source == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json"
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "hooks.json"


def launch_command():
    if getattr(sys, "frozen", False):
        return [str(Path(os.environ.get("CLAWD_TANK_LAUNCHER", sys.executable)).resolve())]
    return [sys.executable, str(LAUNCHER)]


def _our_hook(handler, source):
    if not isinstance(handler, dict) or handler.get("statusMessage") != STATUS:
        return False
    if source == "claude":
        exe = handler.get("command", "")
        args = handler.get("args")
    else:
        command = handler.get("command")
        if not isinstance(command, str):
            return False
        try:
            parts = shlex.split(command)
            if not parts:
                return False
            exe, *args = parts
        except ValueError:
            return False
    if not isinstance(args, list) or not isinstance(exe, str) or args[-2:] != ["hook", source]:
        return False
    if len(args) == 5 and isinstance(args[0], str):
        path = Path(args[0])
        return path.parts[-2:] == ("host", "habitat.py") and args[1] == "--state-dir"
    return len(args) == 4 and args[0] == "--state-dir" and Path(exe).stem == "clawd-tank"


def expected_handler(source, state_dir):
    argv = [*launch_command(), "--state-dir", str(state_dir), "hook", source]
    handler = {"type": "command", "statusMessage": STATUS, "timeout": 3}
    if source == "claude":
        handler.update(command=argv[0], args=argv[1:])
    else:
        handler["command"] = shlex.join(argv)
        if os.name == "nt":
            handler["commandWindows"] = _windows_command(argv)
    return handler


def configure(source: str, state_dir: Path, *, remove: bool = False, path: Path | None = None):
    path = path or config_path(source)
    settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError(f"Invalid hooks configuration in {path}")
    if remove and "hooks" not in settings:
        return path
    before = json.dumps(settings)
    hooks = settings.setdefault("hooks", {})
    handler = expected_handler(source, state_dir)

    for event in HOOKS[source]:
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"Invalid {event} hook groups in {path}")
        kept = []
        for group in entries:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept.append(group)
                continue
            others = [h for h in group["hooks"] if not _our_hook(h, source)]
            if others == group["hooks"]:
                kept.append(group)
            elif others:
                kept.append({**group, "hooks": others})
        if not remove:
            group = {"hooks": [handler]}
            if event == "Notification":
                group["matcher"] = "idle_prompt"
            kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if (not remove or path.exists()) and json.dumps(settings) != before:
        write_json_atomic(path, settings)
    return path


def forward(source: str, state_dir: Path, stream) -> None:
    """A closed habitat is normal. Hook output must never steer an agent."""
    try:
        payload = json.load(stream)
        if isinstance(payload, dict) and re.fullmatch("[0-9a-f]{32}", str(payload.get("habitat_check", ""))) and "hook_event_name" not in payload:
            from .desktop import control
            if control(state_dir, "ping"):
                print(payload["habitat_check"], file=sys.stderr)
            return
        signal = normalize(source, payload)
        if signal is None:
            return
        from .inbox import enqueue
        try:
            info = json.loads((state_dir / "connection.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        if not info or info.get("inbox"):
            enqueue(state_dir, signal)
            if not info:
                return
        connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=0.8)
        try:
            target = "/internal/drain" if info.get("inbox") else "/internal/activity"
            connection.request("POST", target, b"" if info.get("inbox") else json.dumps(asdict(signal)),
                               {"Content-Type": "application/json", "Authorization": "Bearer " + info["key"]})
            response = connection.getresponse()
            response.read()
            if response.status != 204 and not info.get("inbox"):
                enqueue(state_dir, signal)
        except (OSError, http.client.HTTPException):
            if not info.get("inbox"):
                enqueue(state_dir, signal)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, http.client.HTTPException, ValueError, KeyError, TypeError):
        return
