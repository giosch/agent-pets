"""Install observational hooks and forward one hook's stdin to the local host."""
import http.client
import json
import os
from dataclasses import asdict
from pathlib import Path
import shlex
import sys

from clawd_tank_daemon.session_store import write_json_atomic
from .adapters import HOOKS, normalize

LAUNCHER = Path(__file__).resolve().parents[1] / "habitat.py"
STATUS = "Updating Clawd Tank habitat"


def config_path(source: str) -> Path:
    if source == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json"
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "hooks.json"


def configure(source: str, state_dir: Path, *, remove: bool = False, path: Path | None = None):
    path = path or config_path(source)
    settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError(f"Invalid hooks configuration in {path}")
    before = json.dumps(settings)
    hooks = settings.setdefault("hooks", {})
    argv = [sys.executable, str(LAUNCHER), "--state-dir", str(state_dir), "hook", source]
    handler = {"type": "command", "statusMessage": STATUS, "timeout": 3}
    if source == "claude":
        handler.update(command=argv[0], args=argv[1:])
    else:
        handler["command"] = shlex.join(argv)
        if os.name == "nt":
            # Codex's default Windows hook runner wraps this line in cmd.exe /S /C.
            handler["commandWindows"] = " ".join(f'"{arg}"' for arg in argv)

    for event in HOOKS[source]:
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"Invalid {event} hook groups in {path}")
        kept = []
        for group in entries:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept.append(group)
                continue
            others = [h for h in group["hooks"] if not
                      (isinstance(h, dict) and h.get("statusMessage") == STATUS)]
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
        info = json.loads((state_dir / "connection.json").read_text(encoding="utf-8"))
        signal = normalize(source, json.load(stream))
        if signal is None:
            return
        connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=0.8)
        try:
            connection.request("POST", "/internal/activity", json.dumps(asdict(signal)),
                               {"Content-Type": "application/json", "Authorization": "Bearer " + info["key"]})
            connection.getresponse().read()
        finally:
            connection.close()
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
        return
