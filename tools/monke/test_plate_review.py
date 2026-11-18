"""Regression cases for accepting only a reviewed, unchanged plate."""
import unittest
from .plate_review import decision


class PlateGateTests(unittest.TestCase):
    def setUp(self):
        self.digest = "cut-a"
        self.technical = {"candidate": self.digest, "result": "pass"}
        self.reports = {
            role: {"candidate": self.digest, "role":role, "model":"gpt-6.2-astra",
                   "effort":"high", "agent":"test/"+role, "blockers":[], "verdict":"pass",
                   "evidence":[{"pose":"touch","observation":"Finger stays above button"},
                               {"pose":"wait","observation":"Tail holds the wrist"}]}
            for role in ("motion","art")}

    def state(self):
        return decision(self.digest,self.technical,self.reports)

    def test_happy_path(self):
        self.assertEqual(self.state(),"accepted_for_batch")

    def test_new_cut_invalidates_technical_and_visual_results(self):
        self.digest="cut-b"
        self.assertEqual(self.state(),"needs_technical_check")
        self.technical["candidate"]=self.digest
        self.assertEqual(self.state(),"needs_review")

    def test_one_model_invocation_cannot_supply_both_votes(self):
        self.reports["art"]["agent"]=self.reports["motion"]["agent"]
        self.assertEqual(self.state(),"needs_review")

    def test_unresolved_disagreement_requires_work(self):
        for decision_value in ("revise","uncertain"):
            self.reports["art"]["verdict"]=decision_value
            self.assertEqual(self.state(),"revise")

    def test_blanket_praise_and_missing_receipt_cannot_pass(self):
        self.reports["art"]["evidence"]=[]
        self.assertEqual(self.state(),"needs_review")
        del self.reports["art"]
        self.assertEqual(self.state(),"needs_review")
