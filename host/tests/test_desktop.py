"""Recovery guarantees for installed desktop hooks and host updates."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_pets_habitat.adapters import Signal
from agent_pets_habitat.hooks import configure
from agent_pets_habitat.inbox import drain, enqueue
from agent_pets_habitat import installation
from agent_pets_habitat.model import Habitat


class DesktopTests(unittest.TestCase):
    def test_missing_end_hook_reconciles_after_host_restart(self):
        import subprocess
        import sys
        from agent_pets_habitat.presence import process_info, owner_exited
        with TemporaryDirectory() as temp, subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"]) as child:
            try:
                start = process_info(child.pid)[2]
                self.assertTrue(owner_exited(child.pid, start + "-older"))
                path = Path(temp) / "sessions.json"
                habitat = Habitat(path)
                habitat.apply(Signal("claude", "tracked", "approval", owner_pid=child.pid, owner_start=start))
                habitat.apply(Signal("codex", "other", "open"))
                habitat = Habitat(path)
                habitat.reconcile_owners()
                self.assertEqual(len(habitat.snapshot()["sessions"]), 2)
                child.terminate()
                child.wait(10)
                habitat.reconcile_owners()
                self.assertEqual([s["id"] for s in Habitat(path).snapshot()["sessions"]], ["codex:other"])
                self.assertEqual(habitat.feed[-1]["kind"], "owner_exit")
            finally:
                if child.poll() is None:
                    child.terminate()

    def test_interrupted_candidate_preserves_running_installation(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            root = directory / "app"
            root.mkdir()
            (root / ".habitat-install").write_text(installation.MARKER)
            (root / "current").write_text("a" * 20)
            payload = directory / "incomplete"
            payload.mkdir()
            (payload / "release.json").write_text(json.dumps({"version":"0.2.0","files":{"missing":"digest"}}))
            with patch.object(installation, "install_root", return_value=root), patch.object(installation, "stop_for_upgrade") as stop:
                with self.assertRaises(FileNotFoundError):
                    installation.activate(payload, directory / "state")
                stop.assert_not_called()
            self.assertEqual((root / "current").read_text(), "a" * 20)

    def test_first_real_event_can_arrive_after_its_session_was_closed(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / "sessions.json"
            habitat = Habitat(path)
            initial = habitat.snapshot()
            enqueue(directory, Signal("claude", "already-closed", "close"))
            drain(directory, habitat)
            restored = Habitat(path)
            self.assertEqual(restored.snapshot(), initial)
            self.assertEqual(restored.last_events["claude"]["kind"], "close")
            self.assertGreater(restored.last_events["claude"]["time"], 0)

    def test_restart_with_unacknowledged_live_moment_and_offline_close(self):
        with TemporaryDirectory() as temp:
            d = Path(temp)
            h = Habitat(d/"sessions.json")
            enqueue(d, Signal("codex","keep","open"))
            enqueue(d, Signal("claude","close","open"))
            drain(d,h)
            keep = h.snapshot()["sessions"][0]
            # A crash between the durable state commit and the inbox acknowledgement.
            enqueue(d,Signal("codex","keep","retry"))
            original = h.apply
            def crash(*args):
                original(*args)
                raise RuntimeError("simulated interruption")
            with patch.object(h,"apply",side_effect=crash):
                with self.assertRaises(RuntimeError):
                    drain(d,h)
            saved = h.sequence
            enqueue(d, Signal("claude","close","close"))
            restored = Habitat(d/"sessions.json")
            drain(d,restored)
            self.assertEqual(restored.sequence,saved+1)
            self.assertEqual(restored.subscribe().get()["sessions"],[keep])
            self.assertEqual(restored.last_events["claude"]["kind"],"close")

    def test_migration_preserves_other_handlers_and_does_not_duplicate_ours(self):
        with TemporaryDirectory() as temp:
            d=Path(temp)
            for source in ("claude","codex"):
                config=d/(source+".json")
                existing={"hooks":{"Stop":[{"hooks":[{"type":"command","command":"someone-else"}]}]}}
                config.write_text(json.dumps(existing))
                configure(source,d,path=config)
                with patch("agent_pets_habitat.hooks.launch_command",return_value=[str(d/"agent-pets")]):
                    configure(source,d,path=config)
                    one=config.read_bytes()
                    configure(source,d,path=config)
                    self.assertEqual(one,config.read_bytes())
                    self.assertEqual(len(json.loads(one)["hooks"]["Stop"]),2)
                    configure(source,d,path=config,remove=True)
                    self.assertEqual(json.loads(config.read_text()),existing)
