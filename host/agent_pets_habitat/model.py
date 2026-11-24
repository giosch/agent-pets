"""Reduce agent observations into durable sessions and transient display events."""
import json
import time
import uuid
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock

from agent_pets_daemon.session_store import write_json_atomic
from .adapters import Signal

VERSION = 1


@dataclass
class Session:
    id: str
    order: int
    base: str = "idle"
    attention: str = "none"
    turn: str = ""
    previous_turns: list[str] = field(default_factory=list)
    calls: dict[str, str] = field(default_factory=dict)
    call_tools: dict[str, str] = field(default_factory=dict)
    call_metadata: dict[str, dict] = field(default_factory=dict)
    background: dict[str, str] = field(default_factory=dict)
    waits: dict[str, str] = field(default_factory=dict)
    helpers: list[str] = field(default_factory=list)

    fork_seen: bool = False
    owner_pid: int = 0
    owner_start: str = ""
    activity_since: float = 0
    progress_done: int = -1
    progress_total: int = 0
    progress_kind: str = ""

    def public(self) -> dict:
        active = self.calls or self.background
        activity = next(reversed(active.values())) if active else self.base
        if self.helpers and activity in {"idle", "working"}:
            activity = "coordinating"
        attention = next(iter(self.waits.values()), self.attention)
        if self.background and attention == "ready":
            attention = "none"
        result = {"id": self.id, "order": self.order, "activity": activity,
                  "attention": attention, "helpers": len(self.helpers), "active_calls": len(self.calls) + len(self.background)}
        if self.activity_since > 0:
            result["activity_since"] = self.activity_since
        if self.progress_total > 0:
            result.update(progress_done=self.progress_done, progress_total=self.progress_total, progress_kind=self.progress_kind)
        return result

    def finish(self, attention: str) -> None:
        self.waits.clear()
        self.calls.clear()
        self.call_tools.clear()
        self.call_metadata.clear()
        self.base = "idle"
        self.attention = attention

    def observe(self, signal: Signal) -> str | None:
        kind = signal.kind
        if kind == "fork" and not self.fork_seen:
            self.fork_seen = True
            return "forked"
        if kind == "helper_join":
            if signal.ref not in self.helpers:
                self.helpers.append(signal.ref)
            return None
        if kind == "helper_leave":
            if signal.ref in self.helpers:
                self.helpers.remove(signal.ref)
            return None
        # Autonomous goal turns can start without UserPromptSubmit. UUIDv7
        # timestamps provide ordering; stale/unknown IDs never release a wait.
        if signal.turn and self.turn and signal.turn != self.turn and kind != "prompt":
            try:
                current, incoming = uuid.UUID(self.turn), uuid.UUID(signal.turn)
                newer = current.version == incoming.version == 7 and (incoming.int >> 80) > (current.int >> 80)
            except ValueError:
                newer = False
            if newer and kind in {"tool", "question", "approval"}:
                self.previous_turns = (self.previous_turns + [self.turn])[-16:]
                self.turn = signal.turn
                self.finish("none")
                self.base = "working"
        if self.attention in {"ready", "failure"} and kind in {
            "tool", "question", "approval", "done", "tool_error", "retry", "compact",
        }:
            return None
        if signal.turn and signal.turn != self.turn:
            if signal.turn in self.previous_turns:
                return None
            if self.turn and kind != "prompt":
                return None
            if self.turn:
                self.previous_turns = (self.previous_turns + [self.turn])[-16:]
            self.turn = signal.turn

        # Approval hooks may identify a tool without supplying its call ID.
        call = signal.ref or signal.tool or "_"
        if signal.finished_background:
            self.background.pop(signal.finished_background, None)
        if kind == "prompt":
            self.progress_done, self.progress_total, self.progress_kind = -1, 0, ""
            self.finish("none")
            self.base = "working"
        elif kind in {"tool", "question", "approval"}:
            self.attention = "none"
            self.base = "working"
            if kind == "tool":
                self.calls[call] = signal.activity or "working"
                self.call_tools[call] = signal.tool
            else:
                if kind == "approval" and not signal.ref:
                    candidates = [ref for ref, name in self.call_tools.items() if name == signal.tool]
                    if signal.command_key:
                        exact = [ref for ref in candidates if self.call_metadata.get(ref, {}).get("command_key") == signal.command_key]
                        candidates = exact
                        if not exact:
                            call = "command:" + signal.command_key
                    if len(candidates) == 1:
                        call = candidates[0]
                self.waits[call] = kind
        elif kind == "approval_resolved":
            if self.waits.get(call) == "approval":
                self.waits.pop(call)
        elif kind in {"done", "tool_error"}:
            if kind == "done" and signal.progress_kind:
                self.progress_done, self.progress_total, self.progress_kind = signal.progress_done, signal.progress_total, signal.progress_kind
            if kind == "done" and signal.background_ref:
                self.background[signal.background_ref] = self.calls.get(call, signal.activity or "executing")
            self.calls.pop(call, None)
            self.call_tools.pop(call, None)
            self.call_metadata.pop(call, None)
            self.waits.pop(call, None)
            if signal.tool and signal.tool not in self.call_tools.values():
                self.waits.pop(signal.tool, None)
            if kind == "tool_error" and self.attention == "none":
                return "setback"
        elif kind == "ready":
            if signal.background_tasks is not None:
                self.background = signal.background_tasks.copy()
            if self.attention == "failure":
                return None
            first = self.attention != "ready"
            self.finish("ready" if not self.background else "none")
            return "completed" if first and not self.background else None
        elif kind == "idle_reminder":
            if self.base == "idle" and not self.background and not self.waits and self.attention != "failure":
                self.finish("ready")
        elif kind == "failure":
            self.finish("failure")
        elif kind == "interrupt":
            self.finish("none")
            return "interrupted"
        elif kind == "compact":
            return "compacted"
        elif kind == "retry":
            return "setback"
        return None


class Habitat:
    """Serialize state commits, snapshot subscriptions and publication under one lock."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = Lock()
        self.listeners: dict[Queue, bool] = {}
        self.feed = deque(maxlen=200)
        self.sessions: dict[str, Session] = {}
        self.closed: list[str] = []
        self.transient_forks: list[str] = []
        self.sequence = 0
        self.next_order = 0
        self.checkpoint = ("", 0)
        self.last_events = {}
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["version"] != VERSION:
                raise ValueError("Unsupported habitat state version")
            self.sessions = {s["id"]: Session(**s) for s in data["sessions"]}
            self.sequence = data["sequence"]
            self.next_order = data["next_order"]
            self.closed = data["closed"]
            self.transient_forks = data.get("transient_forks", [])
            self.checkpoint = tuple(data.get("checkpoint", self.checkpoint))
            self.last_events = data.get("last_events", {})

    def _snapshot(self) -> dict:
        return {"version": VERSION, "type": "snapshot", "sequence": self.sequence,
                "sessions": [s.public() for s in self.sessions.values()]}

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot()

    def subscribe(self, include_feed=False) -> Queue:
        with self.lock:
            messages = Queue(maxsize=64)
            snapshot = self._snapshot()
            if include_feed:
                snapshot["feed"] = list(self.feed)
            messages.put_nowait(snapshot)
            self.listeners[messages] = include_feed
            return messages

    def unsubscribe(self, messages: Queue) -> None:
        with self.lock:
            self.listeners.pop(messages, None)

    def _transition(self, signal, observed=None):
        sid = f"{signal.source}:{signal.session}"
        old = self.sessions.get(sid)
        sessions = self.sessions.copy()
        closed = self.closed
        next_order = self.next_order
        if signal.kind in {"close", "owner_exit", "dismissed"}:
            if old is None:
                return
            if signal.kind == "owner_exit" and (old.owner_pid, old.owner_start) != (signal.owner_pid, signal.owner_start):
                return
            del sessions[sid]
            closed = (closed + [sid])[-512:]
            message = {"type": "remove", "id": sid}
        else:
            if old is None:
                if sid in closed and signal.kind not in {"open", "prompt", "fork"}:
                    return
                if signal.kind in {"done", "tool_error", "helper_leave", "retry", "interrupt", "compact", "approval_resolved"}:
                    return
                session = Session(sid, next_order)
                next_order += 1
                if sid in closed:
                    closed = [item for item in closed if item != sid]
            else:
                session = deepcopy(old)
            if signal.source == "claude" and signal.owner_pid and signal.owner_start:
                session.owner_pid, session.owner_start = signal.owner_pid, signal.owner_start
            moment = session.observe(signal)
            if signal.kind == "tool" and signal.ref in session.calls and signal.command_key and signal.owner_pid and signal.owner_start:
                session.call_metadata[signal.ref] = {"command_key":signal.command_key,"owner_pid":signal.owner_pid,
                    "owner_start":signal.owner_start,"observed":observed if observed is not None else time.time()}
                pending = "command:" + signal.command_key
                matches = [ref for ref, meta in session.call_metadata.items() if meta["command_key"] == signal.command_key]
                if session.waits.get(pending) == "approval" and len(matches) == 1:
                    session.waits.pop(pending)
                    session.waits[matches[0]] = "approval"
            before, after = old.public() if old else {}, session.public()
            if old is None or (before.get("activity"), before.get("attention")) != (after.get("activity"), after.get("attention")):
                session.activity_since = observed if observed is not None else time.time()
            if old == session and moment is None:
                return
            sessions[sid] = session
            message = {"type": "update", "session": session.public()}
            if moment:
                message["moment"] = moment
        return sessions, closed, next_order, message

    def reconcile_owners(self):
        from .presence import owner_exited
        with self.lock:
            tracked = [(s.id.split(":", 1)[1], s.owner_pid, s.owner_start)
                       for s in self.sessions.values() if s.id.startswith("claude:") and s.owner_pid]
        for session_id, pid, start in tracked:
            if owner_exited(pid, start):
                self.apply(Signal("claude", session_id, "owner_exit", owner_pid=pid, owner_start=start))

    def apply(self, signal: Signal, checkpoint=None, observed=None) -> None:
        with self.lock:
            if checkpoint and self.checkpoint[0] == checkpoint[0] and self.checkpoint[1] >= checkpoint[1]:
                return
            sid = f"{signal.source}:{signal.session}"
            old = self.sessions.get(sid)
            transient_forks = self.transient_forks.copy()
            if signal.transient_fork:
                if sid not in transient_forks:
                    transient_forks = (transient_forks + [sid])[-512:]
            elif signal.kind in {"open", "fork"} and sid in transient_forks:
                # A later real resume/fork may make the same ID a visible chat.
                transient_forks.remove(sid)
            if sid in transient_forks:
                change = self._transition(Signal(signal.source, signal.session, "dismissed")) if old else None
            else:
                change = None if signal.kind == "observe" else self._transition(signal, observed)
            sessions, closed, next_order, message = change or (self.sessions, self.closed, self.next_order, None)
            sequence = self.sequence + int(message is not None)
            last_events = self.last_events.copy()
            if observed is not None:
                last_events[signal.source] = {"time": observed, "kind": signal.kind}
            if self.path and (change or observed is not None or transient_forks != self.transient_forks):
                write_json_atomic(self.path, {
                    "version": VERSION, "sequence": sequence, "next_order": next_order,
                    "closed": closed, "transient_forks": transient_forks,
                    "sessions": [asdict(s) for s in sessions.values()],
                    "checkpoint": checkpoint or self.checkpoint, "last_events": last_events,
                })
            self.checkpoint = checkpoint or self.checkpoint
            self.last_events = last_events
            self.sessions = sessions
            self.closed = closed
            self.transient_forks = transient_forks
            self.next_order = next_order
            self.sequence = sequence
            current = sessions.get(sid)
            entry = {"time": observed if observed is not None else time.time(),
                     "source": signal.source, "event": signal.event, "kind": signal.kind,
                     "pet": (current or old).order + 1 if current or old else None,
                     "arrived": old is None and current is not None,
                     "before": old.public() if old else None, "after": current.public() if current else None,
                     "moment": message.get("moment") if message else None}
            self.feed.append(entry)
            frame = dict(message or {"type": "observation"}, version=VERSION, sequence=sequence)
            for queue, include_feed in self.listeners.items():
                if message is None and not include_feed:
                    continue
                try:
                    queue.put_nowait(dict(frame, observation=entry) if include_feed else frame)
                except Full:
                    # A slow endpoint can recover current truth without playing stale reactions.
                    while True:
                        try:
                            queue.get_nowait()
                        except Empty:
                            break
                    snapshot = self._snapshot()
                    if include_feed:
                        snapshot["feed"] = list(self.feed)
                    queue.put_nowait(snapshot)
