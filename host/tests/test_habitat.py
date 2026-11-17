"""Regression tests for the portable host. Run with Python's unittest from host/."""
import json
from pathlib import Path
from queue import Empty
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from clawd_tank_habitat.adapters import Signal, normalize
from clawd_tank_habitat.hooks import configure
from clawd_tank_habitat.model import Habitat
from clawd_tank_habitat.server import HabitatServer
from clawd_tank_habitat.themes import Themes, install_pack


class HabitatTests(unittest.TestCase):
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
                                    "statusMessage": "Updating Clawd Tank habitat"}]}
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
