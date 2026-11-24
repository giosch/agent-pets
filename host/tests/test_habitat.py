"""Regression tests for the portable host. Run with Python's unittest from host/."""
import json
import io
from pathlib import Path
from queue import Empty
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_pets_habitat.adapters import Signal, normalize
from agent_pets_habitat.hooks import configure
from agent_pets_habitat.model import Habitat
from agent_pets_habitat.server import HabitatServer
from agent_pets_habitat.themes import Themes, install_pack


class HabitatTests(unittest.TestCase):
    def test_changed_codex_hooks_are_reported_for_review(self):
        from agent_pets_habitat.desktop import codex_trust
        from agent_pets_habitat.hooks import config_path, expected_handler
        state = Path("test-habitat-state")
        handler = expected_handler("codex", state)
        hook = {"command": handler.get("commandWindows", handler["command"]),
                "sourcePath": str(config_path("codex")), "trustStatus": "modified", "enabled": True}
        reply = {"id": 2, "result": {"data": [{"hooks": [hook]}]}}
        process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(json.dumps(reply) + "\n"),
                                  kill=lambda: None)
        with patch("agent_pets_habitat.desktop.shutil.which", return_value="codex"), \
             patch("agent_pets_habitat.desktop.subprocess.Popen") as start:
            start.return_value.__enter__.return_value = process
            self.assertEqual(codex_trust(state), "review")

    def test_local_host_starts_without_dns(self):
        with TemporaryDirectory() as directory, patch("socket.getfqdn", side_effect=AssertionError("DNS lookup")):
            with HabitatServer(0, Habitat(), Themes(Path(directory))) as server:
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertGreater(server.server_port, 0)

    def test_agent_adapters_share_meaning(self):
        for source, edit in [("claude", "Edit"), ("codex", "functions.apply_patch")]:
            def event(name, tool, **extra):
                return normalize(source, dict(session_id="s", hook_event_name=name,
                                              tool_name=tool, **extra))
            self.assertEqual(event("PreToolUse", edit).activity, "editing")
            self.assertEqual(event("PreToolUse", "Bash").activity, "executing")
            self.assertEqual(event("PreToolUse", "Bash", tool_input={"command": "rg todo src"}).activity,
                             "inspecting")
            self.assertEqual(event("PreToolUse", "Bash", tool_input={"command": "git status && make"}).activity,
                             "executing")
            self.assertEqual(event("PreToolUse", "mystery").activity, "working")
            self.assertEqual(event("PreToolUse", "mcp__fs__lookup").activity, "external")
            self.assertEqual(event("PermissionRequest", "Bash").kind, "approval")
            self.assertEqual(event("SubagentStart", "", agent_id="h").ref, "h")
            self.assertEqual(event("PreCompact", "").kind, "compact")
        self.assertIsNone(normalize("claude", dict(session_id="s", hook_event_name="Notification",
                                                   notification_type="permission_prompt")))
        self.assertIsNone(normalize("codex", dict(session_id="s", hook_event_name="PostModelRequest",
                                                  status="completed")))
        self.assertIsNone(normalize("codex", dict(session_id="s", hook_event_name="PostToolUse",
                                                  tool_name="request_user_input_async")))

    def test_private_codex_fork_stays_hidden_through_lifecycle_and_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.json"
            h = Habitat(path)
            start = dict(session_id="sample", hook_event_name="SessionStart", source="fork", transcript_path=None)
            h.apply(normalize("codex", start))
            self.assertEqual(h.snapshot()["sessions"], [])
            h = Habitat(path)
            for kind in ("prompt", "tool", "ready", "close", "prompt"):
                h.apply(Signal("codex", "sample", kind))
                self.assertEqual(h.snapshot()["sessions"], [])
            # A real persisted resume is allowed to become visible.
            h.apply(normalize("codex", dict(start, source="resume", transcript_path="rollout.jsonl")))
            self.assertEqual(len(h.snapshot()["sessions"]), 1)

    def test_real_and_legacy_forks_and_ephemeral_cli_sessions_stay_visible(self):
        cases = [
            ("codex", dict(source="fork", transcript_path="rollout.jsonl")),
            ("codex", dict(source="fork")),
            ("codex", dict(source="startup", transcript_path=None)),
            ("claude", dict(source="fork", transcript_path=None)),
        ]
        for source, fields in cases:
            h = Habitat()
            h.apply(normalize(source, dict(session_id="real", hook_event_name="SessionStart", **fields)))
            self.assertEqual(len(h.snapshot()["sessions"]), 1)

    def test_parallel_calls_and_attention(self):
        h = Habitat()
        def send(kind, **values):
            h.apply(Signal("codex", "s", kind, **values))
            return h.snapshot()["sessions"][0]
        send("prompt", turn="a")
        send("question", turn="a", ref="q", tool="request_user_input")
        send("tool", turn="a", ref="x", activity="editing")
        self.assertEqual(send("done", ref="x")["attention"], "question")
        self.assertEqual(send("helper_join", ref="child")["helpers"], 1)
        self.assertEqual(send("helper_join", ref="child")["helpers"], 1)
        self.assertEqual(send("done", ref="q")["attention"], "none")
        send("helper_leave", ref="child")
        send("approval", tool="Bash")
        self.assertEqual(send("done", ref="no-id-on-approval", tool="Bash")["attention"], "none")
        send("ready", turn="a")
        self.assertEqual(send("tool", ref="late", activity="inspecting")["attention"], "ready")
        send("prompt", turn="b")
        self.assertEqual(send("ready", turn="a")["attention"], "none")
        self.assertEqual(send("failure", turn="b")["attention"], "failure")
        self.assertEqual(send("ready", turn="b")["attention"], "failure")

    def test_approval_without_call_id_during_parallel_commands(self):
        h = Habitat()
        for ref in ("first", "second"):
            h.apply(Signal("codex", "s", "tool", ref=ref, tool="Bash", activity="executing"))
        h.apply(Signal("codex", "s", "approval", tool="Bash"))
        h.apply(Signal("codex", "s", "done", ref="first", tool="Bash"))
        self.assertEqual(h.snapshot()["sessions"][0]["attention"], "approval")
        h.apply(Signal("codex", "s", "done", ref="second", tool="Bash"))
        self.assertEqual(h.snapshot()["sessions"][0]["attention"], "none")

    def test_snapshots_order_and_one_shots_survive_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            h = Habitat(path)
            q = h.subscribe()
            self.assertEqual(q.get()["sessions"], [])
            h.apply(Signal("codex", "s", "open"))
            q.get()
            h.apply(Signal("claude", "s", "open"))
            q.get()
            h.apply(Signal("codex", "s", "ready"))
            self.assertEqual(q.get()["moment"], "completed")
            h.apply(Signal("codex", "s", "ready"))
            with self.assertRaises(Empty):
                q.get_nowait()
            saved = h.snapshot()
            self.assertEqual(saved["sessions"][0]["attention"], "ready")
            self.assertNotEqual(saved["sessions"][0]["id"], saved["sessions"][1]["id"])
            self.assertEqual(saved, h.subscribe().get())
            self.assertEqual(saved, Habitat(path).subscribe().get())
            self.assertNotIn("moment", saved)
            h.apply(Signal("codex", "s", "close"))
            h.apply(Signal("codex", "s", "done"))
            self.assertEqual(len(h.snapshot()["sessions"]), 1)

    def test_recoverable_failure_compaction_and_interrupt(self):
        h = Habitat()
        q = h.subscribe()
        q.get()
        h.apply(Signal("codex", "s", "prompt"))
        q.get()
        for event, moment in [("retry", "setback"), ("compact", "compacted"), ("interrupt", "interrupted")]:
            h.apply(Signal("codex", "s", event))
            update = q.get()
            self.assertEqual(update["moment"], moment)
            self.assertEqual(update["session"]["attention"], "none")
            self.assertNotIn("moment", h.snapshot())

    def test_hook_install_preserves_settings_and_is_idempotent(self):
        for source in ("codex", "claude"):
            with TemporaryDirectory() as directory:
                target = Path(directory) / "hooks.json"
                other = {"hooks": [{"type": "command", "command": "my-hook",
                                    "statusMessage": "Updating Agent Pets habitat"}]}
                original = {"hooks": {"Stop": [other]}, "description": "Keep me"}
                target.write_text(json.dumps(original))
                configure(source, target.parent, path=target)
                first = target.read_bytes()
                configure(source, target.parent, path=target)
                self.assertEqual(first, target.read_bytes())
                self.assertEqual(json.loads(first)["hooks"]["Stop"][0], other)
                configure(source, target.parent, path=target, remove=True)
                self.assertEqual(json.loads(target.read_text()), original)
                target.write_text("{broken")
                with self.assertRaises(ValueError):
                    configure(source, target.parent, path=target)
                self.assertEqual(target.read_text(), "{broken")

    def test_fork_moment_and_work_details(self):
        h = Habitat()
        q = h.subscribe()
        q.get()
        def send(event, **fields):
            h.apply(normalize("codex", dict(session_id="child", hook_event_name=event, **fields)))
            return q.get_nowait()
        self.assertEqual(send("SessionStart", source="fork")["moment"], "forked")
        self.assertNotIn("moment", h.subscribe().get())
        h.apply(normalize("codex", dict(session_id="child", hook_event_name="SessionStart", source="fork")))
        self.assertTrue(q.empty())
        for ref, command, expected in [("a", "cargo build", "building"), ("b", "scp readme host:docs", "transferring")]:
            state = send("PreToolUse", tool_name="Bash", tool_use_id=ref, tool_input={"command": command})["session"]
            self.assertEqual(state["activity"], expected)
        self.assertEqual(state["active_calls"], 2)
        self.assertEqual(send("PostToolUse", tool_name="Bash", tool_use_id="b")["session"]["active_calls"], 1)

    def test_artwork_pack_export_and_install(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lib = Themes(root / "packs")
            for key in [("character", "clawd"), ("character", "fox"), ("habitat", "grove")]:
                pack = lib.packs[key]
                archive = root / "pack.zip"
                pack.archive(archive)
                install_pack(archive, root / "packs")
                installed = Themes(root / "packs").packs[key]
                pose = "editing" if key[0] == "character" else "scene"
                self.assertEqual(pack.svg(pose, 1), installed.svg(pose, 1))
                if key[0] == "character":
                    self.assertNotEqual(pack.svg(pose, 0), pack.svg(pose, 1))


if __name__ == "__main__":
    unittest.main()
