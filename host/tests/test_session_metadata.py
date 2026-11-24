"""Local title lookup and bounded paired-display metadata."""
import json
from agent_pets_habitat.session_metadata import SessionMetadata, display_text
from agent_pets_habitat.serial_display import DisplayState

CODEX = "12345678-1234-1234-1234-123456789abc"
CLAUDE = "abcdefab-1234-1234-1234-123456789abc"


def test_native_titles_and_renames(tmp_path):
    codex = tmp_path / "codex"; codex.mkdir()
    claude = tmp_path / "claude"; (claude / "sessions").mkdir(parents=True)
    (codex / "session_index.jsonl").write_text(json.dumps({"id": CODEX, "thread_name": "Display firmware"}) + "\n")
    native = claude / "sessions/123.json"
    native.write_text(json.dumps({"sessionId": CLAUDE, "name": "Local tests"}))
    clock = [0]
    metadata = SessionMetadata(codex, claude, clock=lambda: clock[0])
    assert metadata.resolve({"id": "codex:" + CODEX, "order": 1})["title"] == "Display firmware"
    assert metadata.resolve({"id": "claude:" + CLAUDE, "order": 2})["title"] == "Local tests"
    native.write_text(json.dumps({"sessionId": CLAUDE, "name": "Renamed chat"}))
    clock[0] = 4
    assert metadata.resolve({"id": "claude:" + CLAUDE, "order": 2})["title"] == "Renamed chat"


def test_missing_and_partial_indexes(tmp_path):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "session_index.jsonl").write_text('{partial')
    (tmp_path / "sessions/123.json").write_text('{partial')
    metadata = SessionMetadata(tmp_path, tmp_path)
    assert metadata.resolve({"id": "codex:" + CODEX, "order": 1})["title"] == "Codex session 2"
    assert metadata.resolve({"id": "claude:" + CLAUDE, "order": 2})["source"] == "claude"


def test_unicode_packet_bounds():
    class Metadata:
        def resolve(self, session):
            return {"source": "claude", "title": display_text("\n" + chr(0x1f412) * 200 + "\t")}
    state = DisplayState(Metadata())
    sessions = [{"id": "claude:" + CLAUDE + str(i), "order": i, "activity": "idle", "attention": "ready"} for i in range(3)]
    state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": sessions})
    record = state.record()
    assert len(record) < 4096
    assert record.count(b"\n") == 1
    assert all("\n" not in s["title"] for s in json.loads(record)["sessions"])


def test_metadata_reaches_device_without_changing_activity():
    class Metadata:
        def resolve(self, session): return {"title": "Real session name", "source": "claude"}
    state = DisplayState(Metadata())
    session = {"id": "claude:test", "order": 3, "activity": "executing", "attention": "none", "active_calls": 1}
    state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": [session]})
    wire = json.loads(state.record())["sessions"][0]
    assert wire["title"] == "Real session name"
    assert wire["activity"] == "executing"
    assert "title" not in state.sessions[session["id"]]
