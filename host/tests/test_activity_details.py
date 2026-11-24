"""Activity age, reported progress, autonomous turns and exact approval release."""
import json
import time
from unittest.mock import patch
from agent_pets_habitat.adapters import Signal, normalize
from agent_pets_habitat.model import Habitat
from agent_pets_habitat.serial_display import DisplayState

OLD = "01a20a75-b52e-7c92-8ffa-b21a14d429d2"
NEW = "01a20a7e-ce40-7ad1-8fc7-2ecb1a6840fa"


def test_autonomous_newer_turn_starts_without_prompt_and_older_events_stay_ignored():
    h = Habitat()
    h.apply(Signal("codex", "chat", "prompt", turn=OLD))
    h.apply(Signal("codex", "chat", "ready", turn=OLD))
    h.apply(Signal("codex", "chat", "tool", turn=NEW, ref="new", tool="Bash", activity="executing"))
    state = h.snapshot()["sessions"][0]
    assert (state["activity"], state["attention"], state["active_calls"]) == ("executing", "none", 1)
    h.apply(Signal("codex", "chat", "approval", turn=OLD, ref="old", tool="Bash"))
    assert h.snapshot()["sessions"][0] == state


def test_activity_age_is_preserved_while_same_kind_of_work_continues(tmp_path):
    h = Habitat(tmp_path / "state.json")
    h.apply(Signal("claude", "chat", "prompt"), observed=100)
    h.apply(Signal("claude", "chat", "tool", ref="a", activity="executing"), observed=110)
    h.apply(Signal("claude", "chat", "tool", ref="b", activity="executing"), observed=120)
    assert h.snapshot()["sessions"][0]["activity_since"] == 110
    restored = Habitat(h.path)
    assert restored.snapshot() == h.snapshot()
    restored.apply(Signal("claude", "chat", "done", ref="a"), observed=130)
    assert restored.snapshot()["sessions"][0]["activity_since"] == 110
    restored.apply(Signal("claude", "chat", "done", ref="b"), observed=140)
    assert restored.snapshot()["sessions"][0]["activity_since"] == 140


def test_only_successful_explicit_plan_reports_create_progress():
    payload = {"session_id": "chat", "hook_event_name": "PostToolUse", "tool_name": "functions.update_plan",
               "tool_input": {"plan": [{"step": "private", "status": "completed"}, {"step": "private", "status": "in_progress"}]}}
    signal = normalize("codex", payload)
    assert (signal.progress_done, signal.progress_total, signal.progress_kind) == (1, 2, "steps")
    assert "private" not in str(signal)
    failed = normalize("codex", dict(payload, tool_response={"isError": True}))
    assert failed.progress_kind == ""
    h = Habitat(); h.apply(Signal("codex", "chat", "prompt")); h.apply(signal)
    assert h.snapshot()["sessions"][0]["progress_done"] == 1
    h.apply(Signal("codex", "chat", "prompt"))
    assert "progress_done" not in h.snapshot()["sessions"][0]
    tasks = normalize("claude", {"session_id": "chat", "hook_event_name": "PostToolUse", "tool_name": "TaskList", "tool_response": {"tasks": [{"status": "completed"}]}})
    assert (tasks.progress_done, tasks.progress_total, tasks.progress_kind) == (1, 1, "tasks")


def test_approval_release_is_exact_and_does_not_clear_another_wait():
    h = Habitat(); h.apply(Signal("codex", "chat", "prompt"))
    for ref in ("a", "b"):
        h.apply(Signal("codex", "chat", "tool", ref=ref, tool="Bash", activity="executing"))
        h.apply(Signal("codex", "chat", "approval", ref=ref, tool="Bash"))
    h.apply(Signal("codex", "chat", "approval_resolved", ref="a"))
    assert h.sessions["codex:chat"].waits == {"b": "approval"}
    h.apply(Signal("codex", "chat", "approval_resolved", ref="unknown"))
    assert h.snapshot()["sessions"][0]["attention"] == "approval"
    h.apply(Signal("codex", "chat", "approval_resolved", ref="b"))
    assert h.snapshot()["sessions"][0]["attention"] == "none"
    assert h.snapshot()["sessions"][0]["active_calls"] == 2


def test_device_receives_real_age_clock_and_reported_counts_only():
    state = DisplayState()
    session = {"id": "claude:test", "order": 0, "activity": "executing", "attention": "none", "activity_since": 100,
               "progress_done": 1, "progress_total": 3, "progress_kind": "tasks"}
    state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": [session]})
    with patch("agent_pets_habitat.serial_display.time.time", return_value=120):
        record = json.loads(state.record())
    assert record["sessions"][0]["elapsed"] == 20
    assert record["sessions"][0]["progress_done"] == 1
    assert 0 <= record["local_time"] < 86400
    session.pop("activity_since")
    state.apply({"version": 1, "type": "snapshot", "sequence": 2, "sessions": [session]})
    assert "elapsed" not in json.loads(state.record())["sessions"][0]


def test_pc_activity_token_is_stable_across_clock_ticks_but_tracks_hidden_events():
    state=DisplayState()
    sessions=[{"id":f"claude:{i}","order":i,"activity":"idle","attention":"ready"} for i in range(4)]
    state.apply({"version":1,"type":"snapshot","sequence":7,"sessions":sessions})
    first=json.loads(state.record())
    with patch("agent_pets_habitat.serial_display.time.time",return_value=time.time()+10):
        later=json.loads(state.record())
    assert first["activity_token"]==later["activity_token"]
    state.acknowledge()
    assert json.loads(state.record())["activity_token"]==first["activity_token"]
    state.apply({"version":1,"type":"update","sequence":8,"session":dict(sessions[3],active_calls=1)})
    updated=json.loads(state.record())
    assert updated["activity_token"]!=first["activity_token"]
    assert updated["sessions"]==first["sessions"] # fourth session remains outside visible capacity
    state.apply({"version":1,"type":"update","sequence":8,"session":sessions[3]})
    assert json.loads(state.record())["activity_token"]==updated["activity_token"]
    other=DisplayState();other.apply({"version":1,"type":"snapshot","sequence":8,"sessions":sessions})
    assert json.loads(other.record())["activity_token"]!=updated["activity_token"]
