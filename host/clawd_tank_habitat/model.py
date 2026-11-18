"""Reduce agent observations into durable sessions and transient display events."""
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock

from clawd_tank_daemon.session_store import write_json_atomic
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
    waits: dict[str, str] = field(default_factory=dict)
    helpers: list[str] = field(default_factory=list)

    fork_seen: bool = False

    def public(self) -> dict:
        activity = next(reversed(self.calls.values())) if self.calls else self.base
        if self.helpers and activity in {"idle", "working"}:
            activity = "coordinating"
        attention = next(iter(self.waits.values()), self.attention)
        return {"id": self.id, "order": self.order, "activity": activity,
                "attention": attention, "helpers": len(self.helpers), "active_calls": len(self.calls)}

    def finish(self, attention: str) -> None:
        self.waits.clear()
        self.calls.clear()
        self.call_tools.clear()
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
        if kind == "prompt":
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
                    if len(candidates) == 1:
                        call = candidates[0]
                self.waits[call] = kind
        elif kind in {"done", "tool_error"}:
            self.calls.pop(call, None)
            self.call_tools.pop(call, None)
            self.waits.pop(call, None)
            if signal.tool and signal.tool not in self.call_tools.values():
                self.waits.pop(signal.tool, None)
            if kind == "tool_error" and self.attention == "none":
                return "setback"
        elif kind == "ready":
            if self.attention == "failure":
                return None
            first = self.attention != "ready"
            self.finish("ready")
            return "completed" if first else None
        elif kind == "idle_reminder":
            if self.base == "idle" and not self.waits and self.attention != "failure":
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
        self.listeners: set[Queue] = set()
        self.sessions: dict[str, Session] = {}
        self.closed: list[str] = []
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
            self.checkpoint = tuple(data.get("checkpoint", self.checkpoint))
            self.last_events = data.get("last_events", {})

    def _snapshot(self) -> dict:
        return {"version": VERSION, "type": "snapshot", "sequence": self.sequence,
                "sessions": [s.public() for s in self.sessions.values()]}

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot()

    def subscribe(self) -> Queue:
        with self.lock:
            messages = Queue(maxsize=64)
            messages.put_nowait(self._snapshot())
            self.listeners.add(messages)
            return messages

    def unsubscribe(self, messages: Queue) -> None:
        with self.lock:
            self.listeners.discard(messages)

    def _transition(self, signal):
        sid = f"{signal.source}:{signal.session}"
        old = self.sessions.get(sid)
        sessions = self.sessions.copy()
        closed = self.closed
        next_order = self.next_order
        if signal.kind == "close":
            if old is None:
                return
            del sessions[sid]
            closed = (closed + [sid])[-512:]
            message = {"type": "remove", "id": sid}
        else:
            if old is None:
                if sid in closed and signal.kind not in {"open", "prompt", "fork"}:
                    return
                if signal.kind in {"done", "tool_error", "helper_leave", "retry", "interrupt", "compact"}:
                    return
                session = Session(sid, next_order)
                next_order += 1
                if sid in closed:
                    closed = [item for item in closed if item != sid]
            else:
                session = deepcopy(old)
            moment = session.observe(signal)
            if old == session and moment is None:
                return
            sessions[sid] = session
            message = {"type": "update", "session": session.public()}
            if moment:
                message["moment"] = moment
        return sessions, closed, next_order, message

    def apply(self, signal: Signal, checkpoint=None, observed=None) -> None:
        with self.lock:
            if checkpoint and self.checkpoint[0] == checkpoint[0] and self.checkpoint[1] >= checkpoint[1]:
                return
            change = self._transition(signal)
            if change is None and observed is None:
                return
            sessions, closed, next_order, message = change or (self.sessions, self.closed, self.next_order, None)
            sequence = self.sequence + int(message is not None)
            last_events = self.last_events.copy()
            if observed is not None:
                last_events[signal.source] = {"time": observed, "kind": signal.kind}
            if self.path:
                write_json_atomic(self.path, {
                    "version": VERSION, "sequence": sequence, "next_order": next_order,
                    "closed": closed, "sessions": [asdict(s) for s in sessions.values()],
                    "checkpoint": checkpoint or self.checkpoint, "last_events": last_events,
                })
            self.checkpoint = checkpoint or self.checkpoint
            self.last_events = last_events
            self.sessions = sessions
            self.closed = closed
            self.next_order = next_order
            self.sequence = sequence
            if message is None:
                return
            message.update(version=VERSION, sequence=sequence)
            for queue in self.listeners:
                try:
                    queue.put_nowait(message)
                except Full:
                    # A slow endpoint can recover current truth without playing stale reactions.
                    while True:
                        try:
                            queue.get_nowait()
                        except Empty:
                            break
                    queue.put_nowait(self._snapshot())
