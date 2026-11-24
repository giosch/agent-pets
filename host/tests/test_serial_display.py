"""USB snapshot selection and framing regressions, independent of hardware."""
import json
import unittest

from agent_pets_habitat.serial_display import DisplayState, display_snapshot


class SerialDisplayTests(unittest.TestCase):
    def test_hidden_alert_is_promoted_and_snapshot_is_complete(self):
        sessions = [{"id": str(i), "order": i, "activity": "editing", "attention": attention}
                    for i, attention in enumerate(("none", "ready", "none", "approval"))]
        first = json.loads(display_snapshot({"version": 1, "type": "snapshot", "sessions": sessions}))
        self.assertEqual([s["id"] for s in first["sessions"]], ["0", "1", "3"])
        self.assertEqual(first["total"], 4)
        self.assertEqual(first["sessions"][0]["helpers"], 0)
        empty = json.loads(display_snapshot({"version": 1, "type": "snapshot", "sessions": []}))
        self.assertEqual(empty["sessions"], [])
        self.assertEqual(empty["total"], 0)

    def test_turns_keep_pet_identity_and_positions_for_both_harnesses(self):
        state = DisplayState()
        sessions = [
            {"id": "codex:chat", "order": 94, "activity": "editing", "attention": "none"},
            {"id": "claude:chat", "order": 96, "activity": "idle", "attention": "ready"},
        ]
        state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": sessions})
        expected = [(s["id"], s["order"]) for s in sessions]
        sequence = 1
        for source in ("codex", "claude", "codex", "claude"):
            session = next(s for s in sessions if s["id"].startswith(source + ":"))
            for attention in ("none", "approval", "ready"):
                sequence += 1
                state.apply({"version": 1, "type": "update", "sequence": sequence,
                             "session": dict(session, attention=attention)})
                self.assertEqual([(s["id"], s["order"]) for s in json.loads(state.record())["sessions"]], expected)

    def test_identity_cannot_break_newline_framing(self):
        session = {"id": "codex:a\n雪", "order": 0, "activity": "idle", "attention": "none", "helpers": 2}
        record = display_snapshot({"version": 1, "type": "snapshot", "sessions": [session]})
        self.assertEqual(record.count(b"\n"), 1)
        self.assertEqual(json.loads(record)["sessions"][0], session)
        session["id"] = "x" * 4096
        with self.assertRaises(ValueError):
            display_snapshot({"version": 1, "type": "snapshot", "sessions": [session]})

    def test_unknown_protocol_is_rejected(self):
        with self.assertRaises(ValueError):
            display_snapshot({"version": 2, "type": "snapshot", "sessions": []})

    def test_live_reactions_are_acknowledged_once_and_snapshot_recovers(self):
        state = DisplayState()
        session = {"id": "codex:a", "order": 0, "activity": "editing", "attention": "none",
                   "helpers": 1, "active_calls": 2}
        state.apply({"version": 1, "type": "snapshot", "sequence": 8, "sessions": [session]})
        state.apply({"version": 1, "type": "update", "sequence": 9, "session": session, "moment": "setback"})
        state.apply({"version": 1, "type": "update", "sequence": 10, "session": session})
        wire = json.loads(state.record())["sessions"][0]
        self.assertEqual((wire["moment"], wire["moment_token"], wire["active_calls"]), ("setback", 9, 2))
        state.acknowledge()
        self.assertNotIn("moment", json.loads(state.record())["sessions"][0])
        state.apply({"type": "offline"})
        self.assertFalse(state.online)
        state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": []})
        self.assertTrue(state.online)
        self.assertEqual(json.loads(state.record())["sessions"], [])

    def test_duplicate_updates_do_not_replay_reactions(self):
        state = DisplayState()
        session = {"id": "s", "order": 0, "activity": "idle", "attention": "ready"}
        state.apply({"version": 1, "type": "snapshot", "sequence": 1, "sessions": [session]})
        event = {"version": 1, "type": "update", "sequence": 2, "session": session, "moment": "completed"}
        state.apply(event)
        state.acknowledge()
        state.apply(event)
        self.assertNotIn("moment", json.loads(state.record())["sessions"][0])
