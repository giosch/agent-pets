"""Recovery guarantees for installed desktop hooks and host updates."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from clawd_tank_habitat.adapters import Signal
from clawd_tank_habitat.hooks import configure
from clawd_tank_habitat.inbox import drain, enqueue
from clawd_tank_habitat.model import Habitat


class DesktopTests(unittest.TestCase):
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
                with patch("clawd_tank_habitat.hooks.launch_command",return_value=[str(d/"clawd-tank")]):
                    configure(source,d,path=config)
                    one=config.read_bytes()
                    configure(source,d,path=config)
                    self.assertEqual(one,config.read_bytes())
                    self.assertEqual(len(json.loads(one)["hooks"]["Stop"]),2)
                    configure(source,d,path=config,remove=True)
                    self.assertEqual(json.loads(config.read_text()),existing)
