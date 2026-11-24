"""Read local chat names for the paired display without reading conversation text."""
import json
import os
from pathlib import Path
import time
import uuid


def display_text(value, limit=96):
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())[:limit]
    # JSON escapes can cost twelve bytes per emoji; keep three titles well inside
    # the device's existing 4096-byte record limit.
    while len(json.dumps(value, ensure_ascii=True)) > 258:
        value = value[:-1]
    return value


class SessionMetadata:
    def __init__(self, codex_home=None, claude_home=None, clock=time.monotonic):
        self.codex_home = Path(codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.claude_home = Path(claude_home or os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        self.clock = clock
        self.next_refresh = 0
        self.names = {}

    def _refresh(self):
        now = self.clock()
        if now < self.next_refresh:
            return
        self.next_refresh = now + 3
        names = {}
        try:
            index = self.codex_home / "session_index.jsonl"
            # This index holds IDs and titles, not transcripts. Bound work on large installs.
            with index.open("rb") as f:
                f.seek(max(0, index.stat().st_size - 2 * 1024 * 1024))
                if f.tell():
                    f.readline()
                for line in f:
                    try:
                        item = json.loads(line)
                        title = display_text(item.get("thread_name"))
                        if title and isinstance(item.get("id"), str):
                            names["codex:" + item["id"]] = title
                    except (ValueError, AttributeError):
                        continue
        except OSError:
            pass
        try:
            for path in (self.claude_home / "sessions").glob("*.json"):
                try:
                    if path.stat().st_size > 65536:
                        continue
                    item = json.loads(path.read_text(encoding="utf-8"))
                    title = display_text(item.get("name"))
                    if title and isinstance(item.get("sessionId"), str):
                        names["claude:" + item["sessionId"]] = title
                except (OSError, ValueError, AttributeError):
                    continue
        except OSError:
            pass
        self.names = names

    def resolve(self, session):
        source, _, ident = session["id"].partition(":")
        if source not in {"claude", "codex"}:
            return {}
        try:
            uuid.UUID(ident)
        except ValueError:
            return {}
        self._refresh()
        label = "Claude Code" if source == "claude" else "Codex"
        return {"source": source,
                "title": self.names.get(session["id"], f"{label} session {session['order'] + 1}")}
