"""Claude foreground/background tool lifecycle regressions from local hook traces."""
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_pets_habitat.adapters import normalize
from agent_pets_habitat.model import Habitat
from agent_pets_habitat.serial_display import display_snapshot


class ClaudeActivityTests(unittest.TestCase):
    def setUp(self):
        self.habitat = Habitat()

    def send(self, event, **fields):
        signal = normalize("claude", dict(session_id="local-chat", hook_event_name=event, **fields))
        self.habitat.apply(signal)
        return self.habitat.snapshot()["sessions"][0]

    def background(self, task="shell-a", command="sleep 15"):
        self.send("PreToolUse", tool_name="Bash", tool_use_id=task,
                  tool_input={"command": command, "run_in_background": True})
        return self.send("PostToolUse", tool_name="Bash", tool_use_id=task,
                         tool_input={"command": command, "run_in_background": True},
                         tool_response={"stdout": "private output", "backgroundTaskId": task})

    def test_real_background_trace_stays_active_until_completion(self):
        self.send("UserPromptSubmit")
        running = self.background()
        self.assertEqual((running["activity"], running["active_calls"]), ("executing", 1))
        state = self.send("Stop", background_tasks=[
            {"id": "shell-a", "type": "shell", "status": "running", "command": "sleep 15"}])
        self.assertEqual((state["activity"], state["attention"], state["active_calls"]),
                         ("executing", "none", 1))
        self.assertIsNone(self.habitat.feed[-1]["moment"])
        state = self.send("SubagentStop", agent_id="suggestions")
        self.assertEqual(state["active_calls"], 1)
        self.send("Notification", notification_type="idle_prompt")
        self.assertEqual(self.habitat.snapshot()["sessions"][0]["attention"], "none")
        self.send("UserPromptSubmit", prompt=("<task-notification><task-id>shell-a</task-id>"
                  "<status>completed</status></task-notification>"))
        final = self.send("Stop", background_tasks=[])
        self.assertEqual((final["activity"], final["attention"], final["active_calls"]), ("idle", "ready", 0))
        self.assertEqual(final["id"], running["id"])
        self.assertEqual(final["order"], running["order"])
        self.assertEqual(self.habitat.feed[-1]["moment"], "completed")

    def test_background_survives_next_prompt_and_parallel_foreground(self):
        self.send("UserPromptSubmit")
        self.background("a", "cargo build")
        self.background("b", "scp file host:docs")
        self.send("Stop")  # Older Claude versions omit background_tasks.
        state = self.send("UserPromptSubmit")
        self.assertEqual(state["active_calls"], 2)
        state = self.send("PreToolUse", tool_name="Read", tool_use_id="read")
        self.assertEqual((state["activity"], state["active_calls"]), ("inspecting", 3))
        self.send("PostToolUse", tool_name="Read", tool_use_id="read")
        state = self.send("PostToolUse", tool_name="TaskStop", tool_input={"task_id": "a"},
                          tool_response={"success": True})
        self.assertEqual((state["activity"], state["active_calls"]), ("transferring", 1))
        state = self.send("Stop")
        self.assertEqual(state["attention"], "none")

    def test_task_output_only_clears_a_finished_background_job(self):
        self.send("UserPromptSubmit")
        self.background()
        state = self.send("PostToolUse", tool_name="TaskOutput", tool_input={"task_id": "shell-a"},
                          tool_response={"retrieval_status": "not_ready", "task": {"status": "running"}})
        self.assertEqual(state["active_calls"], 1)
        state = self.send("PostToolUse", tool_name="TaskOutput", tool_input={"task_id": "shell-a"},
                          tool_response={"retrieval_status": "success", "task": {"status": "completed"}})
        self.assertEqual(state["active_calls"], 0)

    def test_authoritative_stop_snapshot_recovers_after_restart(self):
        self.send("UserPromptSubmit")
        self.background()
        with TemporaryDirectory() as tmp:
            self.habitat.path = Path(tmp) / "sessions.json"
            self.send("Stop")
            self.habitat = Habitat(self.habitat.path)
            state = self.send("Stop", background_tasks=[])
            self.assertEqual((state["attention"], state["active_calls"]), ("ready", 0))

    def test_task_metadata_does_not_forward_commands_output_or_descriptions(self):
        signal = normalize("claude", {"session_id": "s", "hook_event_name": "Stop",
            "last_assistant_message": "PRIVATE", "background_tasks": [
                {"id": "a", "type": "shell", "status": "running", "command": "PRIVATE", "description": "PRIVATE"},
                {"id": "b", "type": "shell", "status": "completed", "command": "PRIVATE"}]})
        self.assertNotIn("PRIVATE", json.dumps(asdict(signal)))
        self.assertEqual(signal.background_tasks, {"a": "executing"})

    def test_device_snapshot_includes_running_background_activity(self):
        self.send("UserPromptSubmit")
        self.background()
        self.send("Stop")
        state = json.loads(display_snapshot(self.habitat.snapshot()))["sessions"][0]
        self.assertEqual((state["activity"], state["attention"], state["active_calls"]), ("executing", "none", 1))
