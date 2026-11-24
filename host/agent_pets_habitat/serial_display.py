"""Forward the three highest-priority habitat sessions to the USB pet display."""
import json
import secrets
from queue import Empty, Full, Queue
import threading
import time
from urllib.request import urlopen


def display_snapshot(snapshot):
    """A bounded, complete replacement lets the device recover on every poll."""
    if snapshot.get("version") != 1 or snapshot.get("type") != "snapshot":
        raise ValueError("Expected a habitat v1 snapshot")
    sessions = snapshot["sessions"]

    def priority(session):
        attention = session["attention"]
        rank = 0 if attention in {"question", "approval", "failure"} else 1 if attention == "ready" else 2
        return rank, session["order"]

    # Priority chooses who fits; session order keeps their places stable across turns.
    visible = sorted(sorted(sessions, key=priority)[:3], key=lambda session: session["order"])
    records = []
    for session in visible:
        record = {field: session[field] for field in ("id", "order", "activity", "attention")}
        record["helpers"] = session.get("helpers", 0)
        for field in ("active_calls", "moment", "moment_token", "source", "title", "elapsed", "progress_done", "progress_total", "progress_kind"):
            if field in session:
                record[field] = session[field]
        records.append(record)
    message = {"version": 1, "type": "snapshot", "total": len(sessions), "sessions": records}
    record = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(record) > 4096:
        raise ValueError("Display snapshot exceeds the device's 4096-byte record limit")
    return record


class DisplayState:
    """Recover from snapshots and retain each live reaction until USB acknowledges it."""

    def __init__(self, metadata=None):
        from .session_metadata import SessionMetadata
        self.metadata = metadata if metadata is not None else SessionMetadata()
        self.sessions = {}
        self.online = False
        self.sequence = -1
        self.activity_epoch = secrets.token_hex(4)

    def apply(self, event):
        kind = event.get("type")
        if kind == "offline":
            self.online = False
            self.acknowledge()
            return
        if event.get("version") != 1:
            raise ValueError("Unsupported habitat event version")
        if kind == "snapshot":
            self.sessions = {s["id"]: dict(s) for s in event["sessions"]}
            self.sequence = event["sequence"]
            self.online = True
        elif event["sequence"] > self.sequence:
            self.sequence = event["sequence"]
            if kind == "update":
                session = dict(event["session"])
                previous = self.sessions.get(session["id"], {})
                for field in ("moment", "moment_token"):
                    if field in previous:
                        session[field] = previous[field]
                if event.get("moment"):
                    session.update(moment=event["moment"], moment_token=self.sequence)
                self.sessions[session["id"]] = session
            elif kind == "remove":
                self.sessions.pop(event["id"], None)

    def record(self):
        now = time.time()
        sessions = []
        for session in self.sessions.values():
            record = dict(session, **self.metadata.resolve(session))
            since = record.get("activity_since", 0)
            if isinstance(since, (int, float)) and 0 < since <= now:
                record["elapsed"] = min(2147483647, int(now - since))
            sessions.append(record)
        message = json.loads(display_snapshot({"version": 1, "type": "snapshot", "sessions": sessions}))
        local = time.localtime(now)
        message["local_time"] = local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec
        message["activity_token"] = f"{self.activity_epoch}:{self.sequence}"
        result = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        if len(result) > 4096:
            raise ValueError("Display snapshot exceeds the device record limit")
        return result

    def acknowledge(self):
        for session in self.sessions.values():
            session.pop("moment", None)
            session.pop("moment_token", None)


def read_events(directory, url, messages, stop):
    while not stop.is_set():
        try:
            address = url
            if address is None:
                info = json.loads((directory / "connection.json").read_text(encoding="utf-8"))
                address = f"http://127.0.0.1:{info['port']}"
            with urlopen(address.rstrip("/") + "/v1/events", timeout=8) as response:
                for line in response:
                    if stop.is_set():
                        return
                    if line.startswith(b"data: "):
                        messages.put_nowait(json.loads(line[6:]))
        except (OSError, ValueError, KeyError, Full) as error:
            # A slow USB consumer reconnects for a complete current snapshot.
            while True:
                try:
                    messages.get_nowait()
                except Empty:
                    break
            messages.put_nowait({"type": "offline"})
            print(f"Habitat stream reconnecting: {error}", flush=True)
        stop.wait(2)


def run(port, directory, url=None):
    try:
        import serial
    except ImportError as error:
        raise RuntimeError('Install USB support with python -m pip install "pyserial>=3.5,<4"') from error

    print(f"USB pet display on {port}. Press Ctrl+C to stop.", flush=True)
    messages = Queue(maxsize=128)
    stop = threading.Event()
    state = DisplayState()
    reader = threading.Thread(target=read_events, args=(directory, url, messages, stop), daemon=True)
    reader.start()
    try:
        while True:
            try:
                with serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=2) as device:
                    device.dtr = False
                    device.rts = False
                    device.port = port
                    device.open()
                    announced = False
                    last_record = None
                    while True:
                        while True:
                            try:
                                event = messages.get_nowait()
                                state.apply(event)
                                if event.get("moment"):
                                    break
                            except Empty:
                                break
                        if not state.online:
                            last_record = None
                            time.sleep(0.1)
                            continue
                        record = state.record()
                        if record == last_record:
                            time.sleep(.1)
                            continue
                        device.reset_input_buffer()
                        if device.write(record) != len(record):
                            raise OSError("Incomplete USB write")
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            reply = device.readline()
                            if b'"snapshot_applied"' in reply:
                                if not announced:
                                    print(f"USB display connected, {len(state.sessions)} habitat sessions", flush=True)
                                    announced = True
                                last_record = record
                                state.acknowledge()
                                break
                            if b'"invalid_snapshot"' in reply or b'"record_too_large"' in reply:
                                raise ValueError(f"Device rejected snapshot: {reply.decode('ascii').strip()}")
                        else:
                            raise OSError("USB display did not acknowledge the snapshot")
                        time.sleep(.1)
            except (OSError, ValueError, KeyError, serial.SerialException) as error:
                state.acknowledge()
                print(f"USB bridge waiting: {error}", flush=True)
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
