import json
import os
import shutil
import tempfile
import unittest

from _load import load, example

plan = load("founder-plan", "compile")


class Compile(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "idea.md"), "w") as fh:
            fh.write("# Moss Matcha Bar\n\nA walk-in matcha cafe on King St W.\n")

    def tearDown(self):
        shutil.rmtree(self.d)

    def numbers(self, **change):
        with open(example("founder-cfo", "example.json")) as fh:
            s = json.load(fh)
        s.update(change)
        with open(os.path.join(self.d, "numbers.json"), "w") as fh:
            json.dump(s, fh)

    def panel(self, buys, n=100):
        os.makedirs(os.path.join(self.d, "panel"), exist_ok=True)
        with open(os.path.join(self.d, "panel", "results.json"), "w") as fh:
            json.dump({"buys": buys, "passes": n - buys, "answered": n, "buy_rate": buys / float(n)}, fh)

    def test_no_numbers_is_incomplete(self):
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Incomplete")
        self.assertIn("run /founder-cfo", text)

    def test_good_numbers_and_panel_is_profitable(self):
        self.numbers()
        self.panel(40)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Profitable")
        self.assertTrue(text.startswith("# Moss Matcha Bar · Business plan"))
        self.assertIn("| Profit margin at plan | 38% per cup |", text)
        self.assertIn("40 buy · 60 pass", text)
        self.assertIn("- The buyer panel: run /founder-consumer", text.replace("## Not done yet", ""))

    def test_a_weak_panel_means_not_yet(self):
        self.numbers()
        self.panel(12)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ 12 of 100 simulated buyers buy", text)

    def test_the_plan_says_when_nothing_is_confirmed_with_real_customers(self):
        self.numbers()
        self.panel(90)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Profitable")
        self.assertIn("**Real-customer validation: not started.", text)
        self.assertIn("A simulated screen, not evidence of demand.", text)
        self.assertIn("- Market validation: run /founder-validate", text)

    def test_real_evidence_against_the_idea_overrides_a_good_panel(self):
        from _load import load
        validate = load("founder-validate", "validate")
        import fv_research
        self.numbers()
        self.panel(90)                                        # the simulated buyers love it
        store = validate.Store(os.path.join(self.d, "validation"), create=True)
        store.init_project("Moss Matcha Bar", "A walk-in matcha cafe.")
        seg = store.add_segment({"name": "Commuters", "definition": "d", "criteria": "walks past daily"})
        extracts = []
        for i in range(6):                                    # fixture: six real people who do not have the problem
            pid = fv_research.add_participant(store, {"segment_id": seg, "consent": "recorded", "consent_scope": "notes"})
            notes = os.path.join(self.d, "n%d.txt" % i)
            with open(notes, "w") as fh:
                fh.write("Has not bought a matcha drink in the last year.")
            iv = fv_research.add_interview(store, {"participant_id": pid, "guide_type": "problem_discovery",
                                                   "conducted_on": "2026-10-01", "record_kind": "notes", "record_path": notes})
            extracts.append(fv_research.add_extract(store, {"interview_id": iv, "kind": "behavior",
                                                            "text": "Has not bought a matcha drink in the last year."}))
        claim = store.add_claim({"description": "Commuters want matcha", "dimension": "problem"})
        store.add_evidence({"claim_id": claim, "stance": "contradicts", "category": "D", "ref": {"extracts": extracts},
                            "summary": "None of six bought matcha in the last year"})
        store.commit()
        store.close()
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("**Real-customer validation: No-Go. Based on 6 people interviewed", text)
        self.assertIn("✗ Real customer evidence contradicts the idea (problem)", text)

    def test_losing_money_means_not_yet(self):
        self.numbers(price=3.00)
        v, _ = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")


if __name__ == "__main__":
    unittest.main()
