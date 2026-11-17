"""Tests for founder-validate. Every person, quote, visitor and payment below is an invented test fixture."""

import csv
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from _load import load

validate = load("founder-validate", "validate")   # puts the skill folder on sys.path

import fv_dashboard  # noqa: E402
import fv_experiments as experiments  # noqa: E402
import fv_report  # noqa: E402
import fv_research as research  # noqa: E402
import fv_score as score  # noqa: E402
import fv_stats as stats  # noqa: E402
import fv_synth as synth  # noqa: E402
from fv_store import Store, StoreError  # noqa: E402

CUSTOMER = {
    "business": "Fixture Co", "target": "independent loss adjusters who write more than 20 reports a month",
    "situation": "Writing up an inspection report after visiting a damaged property.",
    "segments": [{"name": "Solo adjuster", "share": 0.6, "income": [50000, 90000]}, {"name": "Small firm", "share": 0.4}],
    "alternatives": ["a Word template", "dictating to an assistant", "nothing"],
    "occupations": ["loss adjuster", "building surveyor"], "age": [28, 60],
}
ARMS = [{"id": "A", "offer": "A service that turns an inspection recording into a draft report you review and approve.",
         "price": 49, "scenario": "You have three reports due this week and see this offer in a trade newsletter."},
        {"id": "B", "offer": "A service that turns an inspection recording into a draft report you review and approve.",
         "price": 99, "scenario": "You have three reports due this week and see this offer in a trade newsletter."}]
CLOCK = "2026-09-30T12:00:00Z"
DESIGN = {
    "learn": "whether qualified adjusters ask for a demo", "population": "loss adjusters reached through a trade newsletter",
    "method": "one landing page with the price and a demo button", "qualification": "says they write reports monthly on the form",
    "primary_metric": {"event": "demo_request", "denominator": "visit"},
    "stopping_rule": {"min_denominator_per_variant": 200, "max_days": 21},
    "decision_rule": {"success_at": 0.05, "fail_below": 0.02},
    "outcomes": {"success": "run a paid pilot", "failure": "rework the offer", "inconclusive": "run it again on a second channel"},
    "cost_estimate": 300, "days_estimate": 14,
}


class Base(unittest.TestCase):
    def setUp(self):
        os.environ["FOUNDER_VALIDATE_NOW"] = CLOCK       # fixtures launch in October 2026: registration must come first
        self.d = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.d, "validation"), create=True)
        self.store.init_project("Fixture Co", "Draft inspection reports from recordings.", 49, "USD")
        self.seg = self.store.add_segment({"name": "Solo adjuster", "definition": "Independent adjusters",
                                           "criteria": "writes 20+ reports a month"})

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.d)
        os.environ.pop("FOUNDER_VALIDATE_NOW", None)

    # fixture helpers --------------------------------------------------------
    def hypothesis(self, area="problem", impact=5, uncertainty=5, cost=1, time=1, statement=None):
        return self.store.add_hypothesis({"area": area, "statement": statement or "%s holds" % area, "impact": impact,
                                          "uncertainty": uncertainty, "test_cost": cost, "test_time": time})

    def claim(self, dimension="problem", hypothesis_id=None):
        return self.store.add_claim({"description": "fixture claim about %s" % dimension, "dimension": dimension,
                                     "hypothesis_id": hypothesis_id, "segment_id": self.seg})

    def interviewed(self, n, kind="behavior", verbatim=False, theme="report time"):
        """n fixture participants, one interview and one extract each. Returns the extract ids."""
        ids = []
        for i in range(n):
            pid = research.add_participant(self.store, {"segment_id": self.seg, "role": "user", "consent": "recorded",
                                                        "consent_scope": "notes and anonymous quotes"})
            path = os.path.join(self.d, "t%s.txt" % pid)
            with open(path, "w") as fh:
                fh.write("Interviewer: When did you last write one up?\nParticipant: Last Tuesday it took me three hours "
                         "to write up one water damage report.\n")
            iv = research.add_interview(self.store, {"participant_id": pid, "guide_type": "problem_discovery",
                                                     "conducted_on": "2026-10-0%d" % (i % 9 + 1), "record_kind": "transcript",
                                                     "record_path": path})
            text = "it took me three hours to write up one water damage report" if verbatim else "Spends about three hours per report."
            ids.append(research.add_extract(self.store, {"interview_id": iv, "kind": kind, "text": text,
                                                         "verbatim": verbatim, "theme": theme}))
        return ids

    def evidence(self, claim, category, ref=None, stance="supports"):
        return self.store.add_evidence({"claim_id": claim, "stance": stance, "category": category, "ref": ref,
                                        "summary": "fixture evidence"})

    def experiment(self, xtype="landing_page", design=None, launch="2026-10-01", **extra):
        xid = experiments.register(self.store, dict({"type": xtype, "title": "fixture test", "design": design or DESIGN,
                                                     "segment_id": self.seg}, **extra))
        if launch:
            experiments.launch(self.store, xid, launch)
        return xid

    def events(self, xid, event, count, qualified=True, variant=None, cost=0):
        experiments.record_events(self.store, xid, [{"event": event, "count": count, "qualified": qualified,
                                                     "occurred_on": "2026-10-05", "origin_record": "fixture export",
                                                     "variant": variant, "cost": cost, "traffic_source": "newsletter"}])

    def pay(self, xid, payer, kind="payment", amount=49.0):
        return experiments.add_transaction(self.store, {"experiment_id": xid, "payer_ref": payer, "kind": kind,
                                                        "amount": amount, "currency": "USD", "occurred_on": "2026-10-06",
                                                        "reference": "fixture-receipt-%s-%s" % (payer, kind), "authorized": True,
                                                        "price_point": 49})

    def lab(self, n=18, repeats=1, stance=None):
        """A fixture synthetic run with answers written by the test, standing in for sub-agents."""
        rid = synth.init_run(self.store, CUSTOMER, ARMS, n=n, seed=11, model="fixture-model", repeats=repeats)
        for stage in synth.STAGES:
            for wave in synth.write_briefs(self.store, rid, stage):
                for pid, rep, _ in wave:
                    card = json.loads(self.store.one("SELECT card_json FROM syn_personas WHERE run_id = ? AND persona_id = ?",
                                                     (rid, pid))["card_json"])
                    if stage == "problem":
                        a = {"id": pid, "stage": "problem", "experiences_problem": "often", "severity": 4,
                             "current_solution": "a Word template", "cost_of_problem": "three hours a report",
                             "questions_for_real_people": ["How long did your last report take?"]}
                    else:
                        s = stance(card, rep) if stance else "interested"
                        a = {"id": pid, "stage": "concept", "arm": card["arm"], "stance": s, "reason_code": "price",
                             "reason": "too dear for me", "main_objection": "the price", "who_pays": "my firm",
                             "price_too_cheap": 10, "price_cheap": 30, "price_expensive": 60, "price_too_expensive": 90,
                             "questions_for_real_people": ["Who signs off on software spending?"]}
                    path = os.path.join(synth.run_dir(self.store, rid), "answers", stage, "%s.r%d.json" % (pid, rep))
                    with open(path, "w") as fh:
                        json.dump(a, fh)
        synth.ingest(self.store, rid)
        return rid

    def level(self, dimension):
        return next(d for d in score.dimensions(self.store) if d["dimension"] == dimension)


class Classification(Base):
    def test_a_category_must_point_at_its_own_table(self):
        c = self.claim()
        with self.assertRaises(sqlite3.IntegrityError):   # a synthetic run dressed up as a purchase
            self.store.db.execute(
                "INSERT INTO evidence (id, claim_id, stance, category, ref_table, method, collected_on, summary, origin, created_at)"
                " VALUES ('E999', ?, 'supports', 'G', 'syn_runs', 'm', '2026-01-01', 's', 'ai', 'now')", (c,))
        with self.assertRaises(StoreError):
            self.evidence(c, "D", {"extracts": []})
        with self.assertRaises(StoreError):
            self.evidence(c, "A", {"run": "R001"})
        with self.assertRaises(StoreError):
            self.evidence(c, "B", {"run": "R404"})

    def test_evidence_cannot_be_promoted_edited_or_deleted(self):
        c = self.claim()
        rid = self.lab()
        e = self.evidence(c, "B", {"run": rid})
        for sql in ("UPDATE evidence SET category = 'D', ref_table = 'interview_extracts' WHERE id = ?",
                    "UPDATE evidence SET summary = 'customers love it' WHERE id = ?",
                    "UPDATE evidence SET stance = 'contradicts' WHERE id = ?", "DELETE FROM evidence WHERE id = ?"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute(sql, (e,))
        self.store.retract_evidence(e, "wrong run")
        with self.assertRaises(sqlite3.IntegrityError):   # a retraction is permanent
            self.store.db.execute("UPDATE evidence SET retracted_at = NULL WHERE id = ?", (e,))
        with self.assertRaises(StoreError):
            self.store.retract_evidence(e, "")

    def test_behaviour_evidence_needs_a_launched_experiment(self):
        c = self.claim("demand")
        xid = self.experiment(launch=None)
        with self.assertRaises(StoreError):
            self.evidence(c, "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"})

    def test_synthetic_volume_never_moves_a_grade(self):
        rid = self.lab(n=500)
        self.assertEqual(self.store.one("SELECT COUNT(*) AS n FROM syn_responses")["n"], 1000)
        for dim in ("problem", "solution", "demand", "behavior", "payment", "segment", "economics"):
            c = self.claim(dim)
            self.evidence(c, "B", {"run": rid})
            self.evidence(c, "A")
        for d in score.dimensions(self.store):
            self.assertEqual(d["level"], "Unknown", d["dimension"])
            self.assertEqual(d["support_tier"], 0)
        v = score.verdict(score.dimensions(self.store))
        self.assertEqual(v["decision"], "No recommendation yet")

    def test_audit_trail_is_chained_and_tamper_evident(self):
        self.interviewed(2)
        ok, n, bad = self.store.verify_audit()
        self.assertTrue(ok)
        self.assertGreater(n, 8)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE audit_log SET actor = 'someone else' WHERE id = 3")
        self.store.db.execute("DROP TRIGGER audit_no_update")        # someone going around the tool
        self.store.db.execute("UPDATE audit_log SET detail_json = '{}' WHERE id = 3")
        ok, _, bad = self.store.verify_audit()
        self.assertFalse(ok)
        self.assertEqual(bad, 3)

    def test_hypotheses_are_versioned(self):
        h = self.hypothesis()
        with self.assertRaises(StoreError):
            self.store.revise_hypothesis(h, {"statement": "new"}, "")
        self.assertEqual(self.store.revise_hypothesis(h, {"statement": "narrower", "uncertainty": 3}, "after 5 interviews"), 2)
        versions = self.store.rows("SELECT * FROM hypothesis_versions WHERE hypothesis_id = ? ORDER BY version", (h,))
        self.assertEqual([v["statement"] for v in versions], ["problem holds", "narrower"])
        self.assertEqual(versions[0]["uncertainty"], 5)


class SampleCounting(Base):
    def test_interviews_count_people_not_extracts(self):
        c = self.claim()
        ids = self.interviewed(3)
        iv = self.store.one("SELECT interview_id FROM interview_extracts WHERE id = ?", (ids[0],))["interview_id"]
        more = [research.add_extract(self.store, {"interview_id": iv, "kind": "behavior", "text": "another note %d" % i})
                for i in range(4)]
        self.evidence(c, "D", {"extracts": ids + more})
        d = self.level("problem")
        self.assertEqual(d["support"]["D"]["units"], 3)
        self.assertEqual(d["level"], "Weakly supported")

    def test_opinions_are_capped_at_weak_and_past_behaviour_is_not(self):
        c = self.claim()
        self.evidence(c, "D", {"extracts": self.interviewed(12, kind="statement")})
        self.assertEqual(self.level("problem")["level"], "Weakly supported")
        self.evidence(c, "D", {"extracts": self.interviewed(5, kind="behavior")})
        self.assertEqual(self.level("problem")["level"], "Moderately supported")
        self.evidence(c, "D", {"extracts": self.interviewed(5, kind="spend")})
        self.assertEqual(self.level("problem")["level"], "Strongly supported")

    def test_a_redacted_participant_is_no_longer_counted(self):
        c = self.claim()
        ids = self.interviewed(5)
        self.evidence(c, "D", {"extracts": ids})
        self.assertEqual(self.level("problem")["level"], "Moderately supported")
        pid = self.store.one("SELECT i.participant_id FROM interview_extracts x JOIN interviews i ON i.id = x.interview_id"
                             " WHERE x.id = ?", (ids[0],))["participant_id"]
        record = self.store.one("SELECT record_path FROM interviews WHERE participant_id = ?", (pid,))["record_path"]
        research.redact_participant(self.store, pid, "withdrew consent")
        self.assertFalse(os.path.exists(record))
        self.assertIn("removed", self.store.one("SELECT text FROM interview_extracts WHERE id = ?", (ids[0],))["text"])
        self.assertEqual(self.level("problem")["support"]["D"]["units"], 4)
        self.assertEqual(self.level("problem")["level"], "Weakly supported")

    def survey(self, rows, min_duration=None):
        inst = {"title": "Report habits", "population": "loss adjusters", "min_duration_s": min_duration, "questions": [
            {"id": "q1", "kind": "screening", "type": "single", "text": "Did you write an inspection report in the last month?",
             "options": ["Yes", "No"], "qualifies": ["Yes"]},
            {"id": "q2", "kind": "behavioral", "type": "single", "text": "How many reports did you write last month?",
             "options": ["1 to 5", "6 to 20", "More than 20"], "ordered": True},
            {"id": "q3", "kind": "stated", "type": "single", "text": "How likely are you to try a drafting service?",
             "options": ["Likely", "Unlikely"], "randomize": True}]}
        sid, _ = research.create_survey(self.store, inst, {"distributed_via": "trade newsletter"})
        path = os.path.join(self.d, "answers-%s.csv" % sid)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["respondent_key", "submitted_at", "duration_s", "q1", "q2", "q3"])
            w.writerows(rows)
        return sid, research.import_responses(self.store, sid, path)

    def test_survey_exclusions_are_transparent_and_rows_are_kept(self):
        rows = [["r%d" % i, "2026-10-0%d" % (i % 9 + 1), 120, "Yes", "More than 20", "Likely"] for i in range(10)]
        rows += [["r0", "2026-10-09", 130, "Yes", "1 to 5", "Unlikely"],      # same respondent again
                 ["r20", "2026-10-02", 90, "No", "1 to 5", "Likely"],         # fails the screener
                 ["r21", "2026-10-02", 95, "Yes", "", "Likely"],              # incomplete
                 ["r22", "2026-10-02", 8, "Yes", "6 to 20", "Likely"]]        # too fast
        sid, report = self.survey(rows, min_duration=30)
        self.assertEqual((report["read"], report["valid"]), (14, 10))
        self.assertEqual(report["excluded"], {"duplicate_respondent": 1, "screened_out": 1, "incomplete": 1, "too_fast": 1})
        self.assertEqual(self.store.one("SELECT COUNT(*) AS n FROM survey_responses")["n"], 14)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("DELETE FROM survey_responses WHERE excluded_reason IS NOT NULL")
        a = research.analyse_survey(self.store, sid)
        self.assertEqual((a["received"], a["valid"]), (14, 10))
        self.assertIn("Not established", a["representative"])
        self.assertEqual(research.count_matching(self.store, sid, "q2", {"in": ["More than 20"]}), (10, 10))
        first = self.store.one("SELECT id FROM survey_responses WHERE excluded_reason IS NULL ORDER BY id")["id"]
        research.exclude_response(self.store, first, "respondent is a co-founder")
        self.assertEqual(research.count_matching(self.store, sid, "q2", {"in": ["More than 20"]}), (9, 9))

    def test_stated_preferences_stay_weak_and_one_survey_is_not_counted_twice(self):
        rows = [["r%d" % i, "2026-10-01", 120, "Yes", "More than 20", "Likely"] for i in range(40)]
        sid, _ = self.survey(rows)
        demand = self.claim("demand")
        self.evidence(demand, "E", {"survey": sid, "question": "q3", "match": {"in": ["Likely"]}})
        self.assertEqual(self.level("demand")["level"], "Weakly supported")       # 40 people saying "likely" is still talk
        problem = self.claim("problem")
        self.evidence(problem, "E", {"survey": sid, "question": "q3", "match": {"in": ["Likely"]}})
        self.assertEqual(self.level("problem")["level"], "Weakly supported")      # stated question, even in 'problem'
        self.evidence(problem, "E", {"survey": sid, "question": "q2", "match": {"in": ["More than 20"]}})
        self.evidence(problem, "E", {"survey": sid, "question": "q2", "match": {"in": ["More than 20", "6 to 20"]}})
        d = self.level("problem")
        self.assertEqual(d["support"]["E"]["strong_units"], 40)                    # not 80
        self.assertEqual(d["level"], "Moderately supported")

    def test_payers_are_counted_net_of_refunds(self):
        xid = self.experiment("preorder", dict(DESIGN, offer_terms="Refundable until delivery; charged at checkout."))
        for p in ("a", "b", "c"):
            self.pay(xid, p, "deposit")
        self.pay(xid, "c", "refund")
        self.pay(xid, "a", "repeat_payment")
        m = experiments.money(self.store, experiment_id=xid)
        self.assertEqual((m["payers"], m["cancelled_or_refunded"], m["repeat_payers"]), (["a", "b"], ["c"], ["a"]))
        self.assertEqual(m["net_revenue"], 147.0)
        c = self.claim("payment")
        self.evidence(c, "G", {"experiment": xid})
        self.assertEqual(self.level("payment")["level"], "Weakly supported")       # 2 net payers; 3 are needed
        self.pay(xid, "d")
        self.assertEqual(self.level("payment")["level"], "Moderately supported")

    def test_a_charge_needs_explicit_authorisation(self):
        xid = self.experiment("preorder", dict(DESIGN, offer_terms="Refundable."))
        with self.assertRaises(StoreError):
            experiments.add_transaction(self.store, {"experiment_id": xid, "payer_ref": "x", "kind": "payment", "amount": 49,
                                                     "currency": "USD", "occurred_on": "2026-10-06", "reference": "r1"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("INSERT INTO transactions (id, payer_ref, kind, amount, currency, occurred_on, reference,"
                                  " authorized, created_at) VALUES ('T9', 'x', 'payment', 1, 'USD', '2026-01-01', 'r', 0, 'now')")


class ReviewFindings(Base):
    """Regressions for defects an independent review found in the first version."""

    def test_a_refund_counts_even_when_the_evidence_leaves_it_out(self):
        xid = self.experiment("preorder", dict(DESIGN, offer_terms="Refundable."))
        paid = [self.pay(xid, "p%d" % i) for i in range(10)]
        for i in range(10):                                   # all ten refunded, filed against no experiment
            experiments.add_transaction(self.store, {"payer_ref": "p%d" % i, "kind": "refund", "amount": 49, "currency": "USD",
                                                     "occurred_on": "2026-10-09", "reference": "refund-%d" % i, "authorized": True})
        c = self.claim("payment")
        self.evidence(c, "G", {"transactions": paid})
        self.evidence(c, "G", {"experiment": xid})
        d = self.level("payment")
        self.assertEqual((d["level"], d["support"]["G"]["units"]), ("Unknown", 0))
        self.assertEqual(experiments.money(self.store, experiment_id=xid)["n_payers"], 0)

    def test_an_unknown_match_operator_is_refused_not_treated_as_match_all(self):
        sid, _ = SampleCounting.survey(self, [["r%d" % i, "2026-10-01", 120, "Yes", "1 to 5", "Likely"] for i in range(40)])
        c = self.claim()
        for ref in ({"survey": sid, "question": "q2", "match": {"equals": "More than 20"}},
                    {"survey": sid, "question": "q2", "match": {"in": 5}},
                    {"survey": sid, "question": "q2", "match": {"in": ["1 to 5"]}, "among": {"in": ["Yes"]}},
                    {"survey": sid, "question": "q2", "match": {"in": ["1 to 5"]}, "among": {"question": "q1", "is": "Yes"}},
                    {"survey": sid, "question": "q2", "match": {}}):
            with self.assertRaises(StoreError):
                self.evidence(c, "E", ref)
        with self.assertRaises(StoreError):
            research.matches("1 to 5", {"equals": "More than 20"})
        self.evidence(c, "E", {"survey": sid, "question": "q2", "match": {"in": ["More than 20"]}})
        self.assertEqual(self.level("problem")["level"], "Unknown")       # nobody gave that answer

    def test_screening_answers_are_not_behaviour_evidence(self):
        sid, _ = SampleCounting.survey(self, [["r%d" % i, "2026-10-01", 120, "Yes", "1 to 5", "Likely"] for i in range(100)])
        self.evidence(self.claim(), "E", {"survey": sid, "question": "q1", "match": {"in": ["Yes"]}})
        self.assertEqual(self.level("problem")["level"], "Weakly supported")   # everyone valid passed the screener
        text = fv_report.report(score.snapshot(self.store))
        behaviour = text.split("_Reported past behaviour_")[1].split("_Stated preferences")[0]
        self.assertNotIn("Did you write an inspection report", behaviour)

    def test_a_funnel_is_counted_once_and_exposure_is_not_an_action(self):
        xid = self.experiment()
        self.events(xid, "visit", 250)
        for event in ("cta_click", "signup", "demo_request"):
            self.events(xid, event, 12)
        c = self.claim("demand")
        for event in ("cta_click", "signup", "demo_request"):
            self.evidence(c, "F", {"experiment": xid, "event": event, "denominator": "visit"})
        d = self.level("demand")
        self.assertEqual((d["support"]["F"]["units"], d["level"]), (12, "Moderately supported"))   # twelve people, not 36
        with self.assertRaises(StoreError):
            self.evidence(c, "F", {"experiment": xid, "event": "visit"})

    def test_a_failed_experiment_cannot_be_filed_as_support(self):
        xid = self.experiment()
        self.events(xid, "visit", 10000)
        self.events(xid, "demo_request", 30)                  # 0.3% against a failure line of 2%
        self.assertEqual(experiments.read(self.store, xid)["outcome"], "failure")
        c = self.claim("demand")
        e = self.evidence(c, "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"})
        self.assertEqual(self.level("demand")["level"], "Unknown")
        item = next(i for i in self.level("demand")["items"] if i["id"] == e)
        self.assertIn("cannot count as support", item["resolved"]["detail"])
        self.evidence(c, "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"}, stance="contradicts")
        self.assertEqual(self.level("demand")["level"], "Contradicted by evidence")
        with self.assertRaises(StoreError):                   # a contradiction needs the people who did not act
            self.evidence(c, "F", {"experiment": xid, "event": "demo_request"}, stance="contradicts")

    def test_a_successful_experiment_cannot_be_filed_as_a_contradiction(self):
        xid = self.experiment()
        self.events(xid, "visit", 250)
        self.events(xid, "demo_request", 20)
        self.evidence(self.claim("demand"), "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"},
                      stance="contradicts")
        self.assertEqual(self.level("demand")["contra_tier"], 0)

    def test_a_re_export_without_keys_cannot_be_imported_twice(self):
        inst = {"title": "t", "population": "p", "questions": [
            {"id": "q1", "kind": "behavioral", "type": "single", "text": "How many reports last month?", "options": ["Few", "Many"]}]}
        sid, _ = research.create_survey(self.store, inst)
        for name, rows in (("a.csv", 20), ("b.csv", 21)):
            path = os.path.join(self.d, name)
            with open(path, "w", newline="") as fh:
                csv.writer(fh).writerows([["q1"]] + [["Many"]] * rows)
            if name == "a.csv":
                research.import_responses(self.store, sid, path)
            else:
                with self.assertRaises(StoreError):
                    research.import_responses(self.store, sid, path)
        self.assertEqual(research.count_matching(self.store, sid, "q1", {"in": ["Many"]}), (20, 20))

    def test_pre_registration_cannot_be_backdated_and_a_closed_test_takes_no_more_data(self):
        xid = self.experiment(launch=None)
        with self.assertRaises(StoreError):
            experiments.launch(self.store, xid, "2020-01-01")
        experiments.launch(self.store, xid, "2026-10-01")
        for bad in ("20261005", "2026-W41-1", "5 October"):
            with self.assertRaises(StoreError):
                experiments.record_events(self.store, xid, [{"event": "visit", "count": 1, "qualified": True,
                                                             "occurred_on": bad, "origin_record": "x"}])
        self.events(xid, "visit", 300)
        self.events(xid, "demo_request", 3)
        experiments.complete(self.store, xid, "failed")
        with self.assertRaises(StoreError):                   # topping up a closed, failed test
            self.events(xid, "demo_request", 40)
        self.assertEqual(experiments.read(self.store, xid)["outcome"], "failure")

    def test_a_hypothesis_is_graded_under_the_caps_of_its_claims(self):
        h = self.hypothesis("commercial", statement="They pay 49 a month")
        self.evidence(self.claim("payment", hypothesis_id=h), "D", {"extracts": self.interviewed(10, kind="spend")})
        got = next(x for x in score.hypotheses(self.store) if x["id"] == h)
        self.assertEqual((got["status"], got["answered"]), ("Unknown", False))
        self.store.revise_hypothesis(h, {"statement": "They pay 99 a month"}, "price raised")
        self.assertFalse(next(x for x in score.hypotheses(self.store) if x["id"] == h)["evidence_predates_wording"])
        os.environ["FOUNDER_VALIDATE_NOW"] = "2026-10-20T00:00:00Z"
        self.store.revise_hypothesis(h, {"statement": "They pay 149 a month"}, "price raised again")
        self.assertTrue(next(x for x in score.hypotheses(self.store) if x["id"] == h)["evidence_predates_wording"])

    def test_a_research_link_is_not_a_demand_signal(self):
        self.evidence(self.claim("problem"), "D", {"extracts": self.interviewed(5)})
        src = self.store.add_research_source({"title": "Report", "url": "https://example.org/r"})
        self.evidence(self.claim("demand"), "C", {"sources": [src]})
        self.assertEqual(self.level("demand")["level"], "Weakly supported")
        self.assertEqual(score.verdict(score.dimensions(self.store))["decision"], "No recommendation yet")

    def test_a_quote_must_match_whole_words_from_the_participant(self):
        pid = research.add_participant(self.store, {"consent": "recorded", "consent_scope": "quotes"})
        path = os.path.join(self.d, "t.txt")
        with open(path, "w") as fh:
            fh.write("Interviewer: So you would definitely buy this today?\n"
                     "Participant: I am unhappy with it and I never use it daily.\n")
        iv = research.add_interview(self.store, {"participant_id": pid, "guide_type": "problem_discovery",
                                                 "conducted_on": "2026-10-01", "record_kind": "transcript", "record_path": path})
        for fake in ("happy with it and I", "ever use it daily", "you would definitely buy this today"):
            with self.assertRaises(StoreError):
                research.add_extract(self.store, {"interview_id": iv, "kind": "statement", "verbatim": True, "text": fake})
        x = research.add_extract(self.store, {"interview_id": iv, "kind": "behavior", "verbatim": True,
                                              "text": "I never use it daily"})
        c = self.claim()
        self.evidence(c, "D", {"extracts": [x]})
        self.assertEqual(self.level("problem")["support"]["D"]["units"], 1)
        research.update_participant(self.store, pid, {"consent": "none"})       # consent withdrawn without a redaction
        self.assertEqual(self.level("problem")["support"]["D"]["units"], 0)
        with self.assertRaises(StoreError):
            research.add_extract(self.store, {"interview_id": iv, "kind": "statement", "text": "more"})

    def test_bad_shapes_are_refused_at_the_door_and_cannot_break_the_record(self):
        for inst in ([], {"title": "t", "population": "p", "questions": ["q1"]},
                     {"title": "t", "population": "p", "questions": [{"id": "q1", "kind": "open", "type": "text"}]},
                     {"title": "t", "population": "p", "van_westendorp": {"cheap": "q1"},
                      "questions": [{"id": "q1", "kind": "pricing", "type": "number", "text": "At what price is it a bargain?"}]},
                     {"title": "t", "population": "p", "gabor_granger": "q1",
                      "questions": [{"id": "q1", "kind": "pricing", "type": "number", "text": "The most you paid last time?"}]}):
            self.assertTrue(research.validate_instrument(inst)[0], inst)
        for design in (dict(DESIGN, variants=["a", "b"], decision_rule={"min_effect": 0.02, "alpha": 5}),
                       dict(DESIGN, decision_rule={"success_at": 0.05, "fail_below": "0.02"}),
                       dict(DESIGN, primary_metric="demo_request"), "a string"):
            self.assertTrue(experiments.validate_design("ab_test" if isinstance(design, dict) and "variants" in design
                                                        else "landing_page", design), design)
        xid = self.experiment("preorder", dict(DESIGN, offer_terms="Refundable."))
        with self.assertRaises(StoreError):
            experiments.add_transaction(self.store, {"experiment_id": xid, "payer_ref": "a", "kind": "payment", "amount": 49,
                                                     "currency": "USD", "occurred_on": "2026-10-06", "reference": "r",
                                                     "authorized": True, "price_point": "49 USD"})
        c = self.claim()
        for ref in ("R001", ["R001"], {"extracts": 5}, {"extracts": ["1"]}, {"sources": "SRC001"}):
            with self.assertRaises(StoreError):
                self.evidence(c, "D" if isinstance(ref, dict) and "extracts" in ref else "C", ref)
        self.assertEqual(fv_report.status_text(score.snapshot(self.store)).splitlines()[0], "Fixture Co: No recommendation yet")

    def test_infinite_and_comma_decimal_numbers_in_a_survey(self):
        q = {"type": "number"}
        self.assertIsNone(research._parse_answer(q, "inf"))
        self.assertIsNone(research._parse_answer(q, "nan"))
        self.assertEqual(research._parse_answer(q, "1,5"), 1.5)
        self.assertEqual(research._parse_answer(q, "1,500"), 1500.0)
        self.assertEqual(research._parse_answer(q, "2 490,00"), 2490.0)

    def test_stored_text_cannot_break_out_of_the_dashboard_data_block(self):
        self.store.add_claim({"description": "<!--<script>alert(1)</script> & </script>", "dimension": "problem"})
        html = fv_dashboard.render(score.snapshot(self.store))
        block = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        self.assertNotIn("<", block)
        self.assertEqual(json.loads(block)["claims"][0]["description"], "<!--<script>alert(1)</script> & </script>")

    def test_replace_cannot_overwrite_a_protected_row_and_exclusions_stick(self):
        c = self.claim("payment")
        e = self.evidence(c, "A")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute(
                "INSERT OR REPLACE INTO evidence (id, claim_id, stance, category, ref_table, method, collected_on, summary,"
                " origin, created_at) VALUES (?, ?, 'supports', 'G', 'transactions', 'm', '2026-01-01', 's', 'ai', 'n')", (e, c))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("INSERT OR REPLACE INTO audit_log (id, at, actor, action, tbl, row_id, detail_json,"
                                  " prev_hash, hash) VALUES (1, 'a', 'b', 'c', 'd', 'e', '{}', '', 'x')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE claims SET dimension = 'problem' WHERE id = ?", (c,))
        sid, _ = SampleCounting.survey(self, [["r1", "2026-10-01", 120, "No", "1 to 5", "Likely"]])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE survey_responses SET excluded_reason = NULL")
        xid = self.experiment()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE experiments SET launched_at = NULL WHERE id = ?", (xid,))

    def test_enthusiasts_never_exceed_the_cap_after_rounding(self):
        mix = {"enthusiast": 2, "skeptic": 2, "satisfied": 2, "no_problem": 1, "price_sensitive": 1, "high_power": 1, "tried_before": 1}
        for n in (10, 11, 13, 17, 23):
            cards = synth.deal(dict(CUSTOMER, archetype_mix=mix), n, 3, ARMS)
            self.assertLessEqual(sum(1 for c in cards if c["archetype"] == "enthusiast"), int(n * 0.2), n)
            self.assertEqual(len(cards), n)


class Interviews(Base):
    def participant(self, consent="recorded"):
        return research.add_participant(self.store, {"segment_id": self.seg, "consent": consent,
                                                     "consent_scope": "recording and quotes" if consent == "recorded" else ""})

    def transcript(self, text, name="t.txt"):
        path = os.path.join(self.d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_no_consent_no_record_and_no_audio(self):
        with self.assertRaises(StoreError):
            research.add_interview(self.store, {"participant_id": self.participant("none"), "guide_type": "problem_discovery",
                                                "conducted_on": "2026-10-01", "record_kind": "notes",
                                                "record_path": self.transcript("notes")})
        with self.assertRaises(StoreError):
            research.add_interview(self.store, {"participant_id": self.participant(), "guide_type": "problem_discovery",
                                                "conducted_on": "2026-10-01", "record_kind": "transcript",
                                                "record_path": self.transcript("x", "call.mp3")})

    def test_a_verbatim_quote_must_be_in_the_transcript(self):
        path = self.transcript("Participant: Honestly I just\n  copy last month’s report and change the address.\n")
        iv = research.add_interview(self.store, {"participant_id": self.participant(), "guide_type": "problem_discovery",
                                                 "conducted_on": "2026-10-01", "record_kind": "transcript", "record_path": path})
        ok = research.add_extract(self.store, {"interview_id": iv, "kind": "behavior", "verbatim": True,
                                               "text": '"I just copy last month\'s report and change the address."'})
        self.assertEqual(self.store.one("SELECT verbatim FROM interview_extracts WHERE id = ?", (ok,))["verbatim"], 1)
        with self.assertRaises(StoreError):   # a tidied-up, more quotable version
            research.add_extract(self.store, {"interview_id": iv, "kind": "statement", "verbatim": True,
                                              "text": "Writing reports is the worst part of my job and I would pay to fix it."})
        s = research.add_extract(self.store, {"interview_id": iv, "kind": "statement", "verbatim": False,
                                              "text": "Reuses old reports as a template."})
        with self.assertRaises(sqlite3.IntegrityError):   # a summary cannot later become a quote
            self.store.db.execute("UPDATE interview_extracts SET verbatim = 1 WHERE id = ?", (s,))

    def test_notes_never_yield_quotes(self):
        iv = research.add_interview(self.store, {"participant_id": self.participant(), "guide_type": "problem_discovery",
                                                 "conducted_on": "2026-10-01", "record_kind": "notes",
                                                 "record_path": self.transcript("She said reports take ages.")})
        with self.assertRaises(StoreError):
            research.add_extract(self.store, {"interview_id": iv, "kind": "statement", "verbatim": True, "text": "reports take ages"})

    def test_analysis_reports_who_was_asked_and_flags_outliers(self):
        self.interviewed(4, theme="report time", verbatim=True)
        self.interviewed(1, theme="photo sorting")
        a = research.analyse_interviews(self.store)
        self.assertEqual((a["participants"], a["by_segment"]), (5, {"Solo adjuster": 5}))
        top, last = a["themes"][0], a["themes"][-1]
        self.assertEqual((top["theme"], top["participants"], top["of"], len(top["quotes"])), ("report time", 4, 5, 4))
        self.assertTrue(last["outlier"])
        self.assertIn("not the market", a["generalise"])

    def test_guide_lint_catches_leading_and_hypothetical_questions(self):
        guide = ("# Guide\n- When did you last write up an inspection?\n- What did you do next?\n"
                 "- Would you use an app that writes the report for you?\n- Don't you think reports take too long?\n"
                 "- How much would you pay for our tool?\n")
        res = research.lint_guide(guide, "problem_discovery")
        self.assertEqual(res["questions"], 5)
        rules = {(f["line"], f["rule"]) for f in res["flags"]}
        self.assertIn((4, "hypothetical"), rules)
        self.assertIn((5, "leading"), rules)
        self.assertIn((6, "stated_wtp"), rules)
        self.assertIn((6, "pitch"), rules)
        self.assertFalse([f for f in res["flags"] if f["line"] in (2, 3)])

    def test_a_survey_with_a_leading_question_is_refused(self):
        inst = {"title": "t", "population": "p", "questions": [
            {"id": "q1", "kind": "stated", "type": "single", "text": "How useful would a faster report tool be?", "options": ["Very", "Not"]}]}
        errors, _ = research.validate_instrument(inst)
        self.assertTrue(any("leading" in e for e in errors))
        inst["questions"][0] = {"id": "q1", "kind": "behavioral", "type": "single", "text": "Would you buy a report tool?",
                                "options": ["Yes", "No"]}
        errors, warnings = research.validate_instrument(inst)
        self.assertTrue(any("asks about the future" in e for e in errors))
        self.assertTrue(any("no screening question" in w for w in warnings))


class Statistics(unittest.TestCase):
    def test_wilson_interval(self):
        lo, hi = stats.wilson(20, 250)
        self.assertAlmostEqual(lo, 0.0524, places=4)
        self.assertAlmostEqual(hi, 0.1203, places=4)
        self.assertEqual(stats.wilson(0, 0), (None, None))
        lo, hi = stats.wilson(0, 50)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.05)                      # zero seen is not zero
        self.assertAlmostEqual(stats.rule_of_three(50), 0.06)

    def test_impossible_counts_are_refused_and_no_data_is_not_zero(self):
        with self.assertRaises(stats.StatsError):
            stats.rate(12, 10)
        self.assertIsNone(stats.rate(0, 0))
        self.assertEqual(stats.describe_rate(0, 0), "no data")
        self.assertEqual(stats.describe_rate(20, 250), "8.0% (20 of 250; 95% interval 5.2% to 12.0%)")

    def test_two_proportions(self):
        t = stats.two_proportions(50, 1000, 80, 1000)
        self.assertAlmostEqual(t["diff"], 0.03)
        self.assertAlmostEqual(t["relative_lift"], 0.6)
        self.assertAlmostEqual(t["p_value"], 0.0065, places=3)
        self.assertTrue(t["ci"][0] > 0 and t["ci"][1] < 0.06)
        small = stats.two_proportions(1, 12, 4, 12)
        self.assertFalse(small["approximation_ok"])

    def test_sample_sizes(self):
        n = stats.sample_size_two_proportions(0.05, 0.02)
        self.assertTrue(2150 < n < 2260, n)                # textbook value is about 2,200 per group
        self.assertEqual(stats.sample_size_one_proportion(0.5, 0.05), 385)
        with self.assertRaises(stats.StatsError):
            stats.sample_size_two_proportions(0.05, 0)

    def test_sign_test_and_price_tools(self):
        self.assertAlmostEqual(stats.sign_test(5, 0), 0.0625)
        self.assertEqual(stats.sign_test(3, 3), 1.0)
        gg = stats.gabor_granger([20, 20, 40, 40, 40, 60, 60, 80, 100, 100])
        self.assertEqual(gg["kind"], "stated")
        self.assertEqual(gg["curve"][0], {"price": 20.0, "share_willing": 1.0, "revenue_index": 20.0})
        self.assertEqual(gg["revenue_max_price"], 40.0)
        self.assertAlmostEqual(stats.arc_elasticity(49, 0.10, 99, 0.05), -0.9867, places=3)
        with self.assertRaises(stats.StatsError):
            stats.gabor_granger([10, 20])


class Experiments(Base):
    def test_an_incomplete_design_cannot_be_registered(self):
        thin = {k: v for k, v in DESIGN.items() if k not in ("decision_rule", "outcomes", "qualification")}
        with self.assertRaises(StoreError) as cm:
            experiments.register(self.store, {"type": "landing_page", "title": "t", "design": thin})
        for word in ("qualification", "decision_rule", "outcomes.failure"):
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(StoreError):   # a pre-order with no written terms
            experiments.register(self.store, {"type": "preorder", "title": "t", "design": DESIGN})

    def test_the_design_locks_at_launch_and_data_before_launch_is_refused(self):
        xid = self.experiment(launch=None)
        with self.assertRaises(StoreError):
            self.events(xid, "visit", 10)
        experiments.launch(self.store, xid, "2026-10-01")
        with self.assertRaises(sqlite3.IntegrityError):    # moving the goalposts
            self.store.db.execute("UPDATE experiments SET design_json = '{}' WHERE id = ?", (xid,))
        with self.assertRaises(StoreError):
            experiments.record_events(self.store, xid, [{"event": "visit", "count": 5, "qualified": True,
                                                         "occurred_on": "2026-09-20", "origin_record": "x"}])
        with self.assertRaises(StoreError):                # qualification must be stated, even as unknown
            experiments.record_events(self.store, xid, [{"event": "visit", "count": 5, "occurred_on": "2026-10-02",
                                                         "origin_record": "x"}])
        experiments.amend(self.store, xid, "extended to 28 days", "newsletter slipped a week")
        self.assertEqual(len(experiments.read(self.store, xid)["amendments"]), 1)

    def test_only_qualified_traffic_enters_the_conversion_rate(self):
        xid = self.experiment()
        self.events(xid, "visit", 250, cost=300)
        self.events(xid, "demo_request", 20)
        self.events(xid, "visit", 4000, qualified=False)   # a viral post: not our customer
        self.events(xid, "demo_request", 35, qualified=False)
        self.events(xid, "visit", 120, qualified=None)
        r = experiments.read(self.store, xid)
        a = r["arms"][0]
        self.assertEqual((a["k"], a["n"], a["unqualified_n"], a["unknown_n"]), (20, 250, 4000, 120))
        self.assertAlmostEqual(a["rate"], 0.08)
        self.assertAlmostEqual(a["cost_per_conversion"], 15.0)
        self.assertEqual(r["outcome"], "success")
        self.assertIn("8.0% (20 of 250", r["reading"])
        self.assertEqual(r["meaning"], "run a paid pilot")
        self.assertEqual(r["sources"]["newsletter"]["unqualified"], 4000)

    def test_generic_traffic_alone_is_unreadable(self):
        xid = self.experiment()
        self.events(xid, "visit", 5000, qualified=None)
        self.events(xid, "demo_request", 400, qualified=None)
        r = experiments.read(self.store, xid)
        self.assertEqual(r["outcome"], "unreadable")
        self.assertIn("says nothing about demand", r["reading"])
        c = self.claim("demand")
        self.evidence(c, "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"})
        self.assertEqual(self.level("demand")["level"], "Unknown")

    def test_too_little_data_and_failure(self):
        xid = self.experiment()
        self.events(xid, "visit", 60)
        r = experiments.read(self.store, xid)
        self.assertEqual(r["outcome"], "not_enough_data")
        self.assertIn("probably below 5.0%", r["reading"])
        self.events(xid, "visit", 240)
        self.events(xid, "demo_request", 3)
        r = experiments.read(self.store, xid)
        self.assertEqual(r["outcome"], "failure")
        self.assertEqual(r["meaning"], "rework the offer")

    def test_inconsistent_counts_are_flagged(self):
        xid = self.experiment()
        self.events(xid, "visit", 10)
        self.events(xid, "demo_request", 25)
        self.assertEqual(experiments.read(self.store, xid)["outcome"], "unreadable")

    def ab(self):
        design = dict(DESIGN, variants=["control", "new"], decision_rule={"min_effect": 0.02, "alpha": 0.05},
                      stopping_rule={"min_denominator_per_variant": 1000, "max_days": 30})
        return self.experiment("ab_test", design)

    def test_no_winner_from_an_early_look(self):
        xid = self.ab()
        self.events(xid, "visit", 100, variant="control")
        self.events(xid, "visit", 100, variant="new")
        self.events(xid, "demo_request", 2, variant="control")
        self.events(xid, "demo_request", 12, variant="new")       # looks great after one day
        r = experiments.read(self.store, xid)
        self.assertTrue(r["interim"])
        self.assertEqual(r["outcome"], "not_enough_data")
        self.assertNotIn("winner", r)
        self.assertEqual(experiments.read(self.store, xid)["looks"], 2)

    def test_a_winner_needs_the_sample_significance_and_a_practical_effect(self):
        xid = self.ab()
        self.events(xid, "visit", 1000, variant="control")
        self.events(xid, "visit", 1000, variant="new")
        self.events(xid, "demo_request", 50, variant="control")
        self.events(xid, "demo_request", 80, variant="new")
        r = experiments.read(self.store, xid)
        self.assertEqual((r["outcome"], r["winner"]), ("success", "new"))
        self.assertAlmostEqual(r["comparisons"][0]["diff"], 0.03)
        self.assertIn("3.0 points", r["reading"])

    def test_a_significant_but_tiny_difference_is_not_a_winner(self):
        design = dict(DESIGN, variants=["control", "new"], decision_rule={"min_effect": 0.05, "alpha": 0.05},
                      stopping_rule={"min_denominator_per_variant": 1000, "max_days": 30})
        xid = self.experiment("ab_test", design)
        self.events(xid, "visit", 20000, variant="control")
        self.events(xid, "visit", 20000, variant="new")
        self.events(xid, "demo_request", 1000, variant="control")
        self.events(xid, "demo_request", 1200, variant="new")
        r = experiments.read(self.store, xid)
        self.assertTrue(r["comparisons"][0]["significant"])
        self.assertEqual(r["outcome"], "inconclusive")
        self.assertNotIn("winner", r)

    def test_a_price_test_reports_each_price_and_elasticity(self):
        design = dict(DESIGN, variants=["low", "high"], price_points={"low": 49, "high": 99},
                      decision_rule={"min_effect": 0.02}, offer_terms="Each visitor is charged the price they saw.",
                      stopping_rule={"min_denominator_per_variant": 500, "max_days": 30})
        xid = self.experiment("price_test", design)
        for v, k in (("low", 60), ("high", 30)):
            self.events(xid, "visit", 600, variant=v)
            self.events(xid, "demo_request", k, variant=v)
        r = experiments.read(self.store, xid)
        self.assertEqual([a["price_point"] for a in r["arms"]], [49, 99])
        self.assertAlmostEqual(r["comparisons"][0]["arc_elasticity"], -0.9867, places=3)
        p = score.pricing(self.store)
        self.assertEqual(p["highest_layer"], 5)


class SyntheticLab(Base):
    def test_dealing_is_reproducible_balanced_and_never_all_fans(self):
        a = synth.deal(CUSTOMER, 90, 4, ARMS)
        self.assertEqual(a, synth.deal(CUSTOMER, 90, 4, ARMS))
        self.assertNotEqual(a, synth.deal(CUSTOMER, 90, 5, ARMS))
        counts = {}
        for c in a:
            counts[c["archetype"]] = counts.get(c["archetype"], 0) + 1
        self.assertEqual(counts, {k: 10 for k in synth.ARCHETYPE_IDS})
        self.assertEqual(sum(1 for c in a if c["arm"] == "A"), 45)
        with self.assertRaises(StoreError):
            synth.deal(dict(CUSTOMER, archetype_mix={"enthusiast": 5, "skeptic": 1, "satisfied": 1, "no_problem": 1,
                                                      "price_sensitive": 1, "high_power": 1}), 90, 4, ARMS)
        with self.assertRaises(StoreError):
            synth.deal(dict(CUSTOMER, archetype_mix={"enthusiast": 1, "high_power": 1}), 90, 4, ARMS)
        with self.assertRaises(StoreError):
            synth.deal(CUSTOMER, 501, 4, ARMS)

    def test_a_promotional_offer_and_an_unrecorded_model_are_refused(self):
        hype = [dict(ARMS[0], offer="The best, revolutionary way to write reports effortlessly!")]
        with self.assertRaises(StoreError):
            synth.init_run(self.store, CUSTOMER, hype, model="m")
        with self.assertRaises(StoreError):
            synth.init_run(self.store, CUSTOMER, ARMS, model="")

    def test_the_problem_stage_never_shows_the_solution(self):
        rid = synth.init_run(self.store, CUSTOMER, ARMS, n=18, seed=3, model="fixture-model")
        waves = synth.write_briefs(self.store, rid, "problem")
        self.assertEqual(sum(len(w) for w in waves), 18)
        with open(waves[0][0][2]) as fh:
            brief = fh.read()
        self.assertIn("Writing up an inspection report", brief)
        self.assertNotIn("draft report you review", brief)
        self.assertNotIn("Price:", brief)
        with open(synth.write_briefs(self.store, rid, "concept")[0][0][2]) as fh:
            concept = fh.read()
        self.assertIn("draft report you review", concept)
        self.assertIn("Agreeable answers are worthless", concept)

    def test_the_run_record_is_frozen_and_complete(self):
        rid = self.lab()
        run = self.store.get("syn_runs", rid)
        self.assertEqual((run["model"], run["seed"], run["n_personas"], run["repeats"]), ("fixture-model", 11, 18, 1))
        self.assertTrue(run["prompt_version"].startswith("lab-1:"))
        self.assertIn("not market statistics", run["persona_method"])
        for sql in ("UPDATE syn_runs SET model = 'better-model' WHERE id = ?", "DELETE FROM syn_runs WHERE id = ?"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute(sql, (rid,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE syn_responses SET answer_json = '{}'")

    def test_the_tally_is_research_material_not_a_conversion_rate(self):
        rid = self.lab()
        t = synth.tally(self.store, rid)
        flat = json.dumps(t)
        for banned in ("buy_rate", "conversion_rate", "purchase_rate"):
            self.assertNotIn(banned, flat)
        self.assertEqual(t["independent_market_observations"], 0)
        self.assertIn("How long did your last report take?", t["questions_for_real_customers"])
        self.assertIn("not a conversion rate", t["concept"]["A"]["calibration_only"]["note"])
        md = synth.results_md(t)
        self.assertIn("**SIMULATED. Not customers.**", md)
        self.assertIn("(simulated) the price", md)
        self.assertNotIn("customers said", md.lower())

    def test_repeats_measure_how_much_answers_wobble(self):
        flip = lambda card, rep: "interested" if (rep == 1 or int(card["id"][1:]) % 2) else "rejects"
        rid = self.lab(n=18, repeats=2, stance=flip)
        t = synth.tally(self.store, rid)
        w = t["concept"]["A"]["wobble"]
        self.assertEqual(w["profiles_repeated"], 9)
        self.assertGreater(w["changed_answer"], 0)
        self.assertEqual(t["concept"]["A"]["answered"], 9)        # repeats are not extra people

    def test_a_bad_answer_file_is_not_filed(self):
        rid = synth.init_run(self.store, CUSTOMER, ARMS, n=10, seed=3, model="fixture-model")
        synth.write_briefs(self.store, rid, "concept")
        path = os.path.join(synth.run_dir(self.store, rid), "answers", "concept", "S001.r1.json")
        with open(path, "w") as fh:
            json.dump({"id": "S001", "stage": "concept", "arm": "Z", "stance": "loves it"}, fh)
        filed, problems = synth.ingest(self.store, rid)
        self.assertEqual((filed, len(problems)), (0, 1))

    def test_a_founder_consumer_panel_imports_as_synthetic(self):
        panel = load("founder-consumer", "panel")
        pd = os.path.join(self.d, "panel")
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "founder-consumer")
        panel.init(pd, os.path.join(here, "customer.example.json"), os.path.join(here, "pitch.example.md"), n=10, seed=5)
        for i in range(1, 11):
            with open(os.path.join(pd, "answers", "P%03d.json" % i), "w") as fh:
                json.dump({"id": "P%03d" % i, "buys": i <= 7, "reason_code": "price", "reason": "r"}, fh)
        rid, filed = synth.import_panel(self.store, pd)
        self.assertEqual(filed, 10)
        self.assertEqual(self.store.get("syn_runs", rid)["kind"], "imported_panel")
        c = self.claim("demand")
        self.evidence(c, "B", {"run": rid})
        self.assertEqual(self.level("demand")["level"], "Unknown")     # 7 of 10 simulated buyers buys nothing


class Calibration(Base):
    def pair(self, n=1, comparable=True, one_run=False):
        stance = lambda card, rep: "interested" if int(card["id"][1:]) % 10 < 7 else "rejects"
        rid = self.lab(stance=stance)
        for i in range(n):
            if i and not one_run:
                rid = self.lab(stance=stance)          # an independent run per comparison
            pid = score.add_prediction(self.store, {"source": "synthetic", "run_id": rid, "prediction_type": "interest_share",
                                                    "measured_what": "share of simulated profiles expressing strong interest",
                                                    "predicted": 0.70, "segment_id": self.seg})
            xid = self.experiment()
            self.events(xid, "visit", 250)
            self.events(xid, "demo_request", 20)
            score.add_outcome(self.store, {"prediction_id": pid, "experiment_id": xid, "event": "demo_request",
                                           "denominator": "visit", "measured_what": "qualified visitors requesting a demo",
                                           "comparable": comparable, "comparable_note": "same segment and offer"})
        return score.calibration(self.store)

    def test_a_prediction_and_a_result_are_set_side_by_side_never_averaged(self):
        c = self.pair()
        p = c["pairs"][0]
        self.assertAlmostEqual(p["predicted"], 0.70)
        self.assertAlmostEqual(p["actual"], 0.08)
        self.assertEqual((p["actual_k"], p["actual_n"]), (20, 250))
        self.assertAlmostEqual(p["difference"], 0.62)
        for key in ("blended", "average", "combined", "adjusted"):
            self.assertFalse([k for k in p if key in k], key)
        self.assertNotIn("39", json.dumps(fv_report.clean(c)))          # (70 + 8) / 2 appears nowhere
        self.assertTrue(any("different things" in r for r in p["possible_reasons"]))
        self.assertTrue(any("lean agreeable" in r for r in p["possible_reasons"]))

    def test_no_calibration_metric_below_five_comparable_pairs(self):
        c = self.pair(n=4)
        self.assertFalse(c["calibrated"])
        self.assertNotIn("mean_signed_error", c["summary"][0])
        self.assertIn("Not calibrated", c["statement"])
        self.assertIn("number of synthetic answers does not change this", c["statement"])

    def test_metrics_appear_with_five_comparable_pairs_and_ignore_incomparable_ones(self):
        c = self.pair(n=5)
        row = c["summary"][0]
        self.assertTrue(c["calibrated"])
        self.assertAlmostEqual(row["mean_signed_error"], 0.62)
        self.assertEqual((row["over"], row["under"]), (5, 0))
        self.assertAlmostEqual(row["sign_test_p"], 0.0625)
        self.assertIn("overestimated by 62.0 points", row["says"])

    def test_one_run_or_one_experiment_is_one_observation_however_often_it_is_filed(self):
        c = self.pair(n=5, one_run=True)                 # five predictions copied from the same synthetic run
        self.assertFalse(c["calibrated"])
        self.assertEqual(c["summary"][0]["comparable_pairs"], 1)
        self.assertEqual([p["counted"] for p in c["pairs"]], [True, False, False, False, False])

    def test_a_prediction_made_once_data_is_coming_in_is_refused(self):
        xid = self.experiment()
        self.events(xid, "visit", 250)
        os.environ["FOUNDER_VALIDATE_NOW"] = "2026-10-08T00:00:00Z"
        pid = score.add_prediction(self.store, {"source": "founder", "prediction_type": "demo_rate",
                                                "measured_what": "my guess", "predicted": 0.08})
        with self.assertRaises(StoreError):
            score.add_outcome(self.store, {"prediction_id": pid, "experiment_id": xid, "event": "demo_request",
                                           "denominator": "visit", "measured_what": "m", "comparable": True, "comparable_note": "n"})
        with self.assertRaises(StoreError):
            score.add_prediction(self.store, {"source": "founder", "prediction_type": "t", "measured_what": "m", "predicted": "10%"})

    def test_incomparable_pairs_never_feed_a_metric(self):
        c = self.pair(n=6, comparable=False)
        self.assertEqual(c["summary"], [])
        self.assertFalse(c["calibrated"])

    def test_a_prediction_cannot_be_written_after_the_result_or_edited(self):
        xid = self.experiment()
        os.environ["FOUNDER_VALIDATE_NOW"] = "2026-10-10T00:00:00Z"
        try:
            experiments.complete(self.store, xid, "done")
            os.environ["FOUNDER_VALIDATE_NOW"] = "2026-10-11T00:00:00Z"
            pid = score.add_prediction(self.store, {"source": "founder", "prediction_type": "demo_rate",
                                                    "measured_what": "my guess", "predicted": 0.08})
        finally:
            os.environ["FOUNDER_VALIDATE_NOW"] = CLOCK
        with self.assertRaises(StoreError):
            score.add_outcome(self.store, {"prediction_id": pid, "experiment_id": xid, "event": "demo_request",
                                           "denominator": "visit", "measured_what": "m", "comparable": True, "comparable_note": "n"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE predictions SET predicted = 0.08 WHERE id = ?", (pid,))

    def test_a_run_can_file_its_own_prediction(self):
        rid = self.lab()
        pid = score.predict_from_run(self.store, rid, "A")
        p = self.store.get("predictions", pid)
        self.assertEqual((p["source"], p["model"], p["price_point"], p["predicted"]), ("synthetic", "fixture-model", 49.0, 1.0))


class Grading(Base):
    def test_the_grade_table(self):
        g = score.grade
        self.assertEqual(g(0, 0), ("Unknown", False))
        self.assertEqual(g(2, 0), ("Moderately supported", False))
        self.assertEqual(g(3, 1), ("Moderately supported", True))
        self.assertEqual(g(1, 1), ("Unknown", True))
        self.assertEqual(g(0, 1), ("Unknown", True))
        self.assertEqual(g(2, 2), ("Contradicted by evidence", True))
        self.assertEqual(g(1, 3), ("Contradicted by evidence", True))
        self.assertEqual(g(3, 2), ("Moderately supported", True))

    def test_contradicting_interviews_outweigh_and_are_never_dropped(self):
        c = self.claim()
        self.evidence(c, "D", {"extracts": self.interviewed(2)})
        e = self.evidence(c, "D", {"extracts": self.interviewed(6, theme="no problem")}, stance="contradicts")
        d = self.level("problem")
        self.assertEqual(d["level"], "Contradicted by evidence")
        self.assertEqual(score.verdict(score.dimensions(self.store))["decision"], "No-Go")
        text = fv_report.report(score.snapshot(self.store))
        section = text.split("## 13. Contradictory evidence")[1].split("## 14.")[0]
        self.assertIn(e, section)

    def test_each_question_only_accepts_evidence_that_can_answer_it(self):
        ids = self.interviewed(10, kind="spend")
        for dim in ("problem", "demand", "payment", "behavior"):
            self.evidence(self.claim(dim), "D", {"extracts": ids})
        self.assertEqual(self.level("problem")["level"], "Strongly supported")
        self.assertEqual(self.level("demand")["level"], "Weakly supported")     # talk, however much
        self.assertEqual(self.level("payment")["level"], "Unknown")
        self.assertEqual(self.level("behavior")["level"], "Unknown")
        self.assertTrue(any("5 more" in m or "more" in m for m in self.level("payment")["missing"]))

    def test_research_alone_is_weak(self):
        s = self.store.add_research_source({"title": "Industry survey", "url": "https://example.org/report", "kind": "report"})
        self.evidence(self.claim("problem"), "C", {"sources": [s]})
        self.assertEqual(self.level("problem")["level"], "Weakly supported")
        self.evidence(self.claim("solution"), "C", {"sources": [s]})
        self.assertEqual(self.level("solution")["level"], "Unknown")            # a report cannot test our solution
        with self.assertRaises(StoreError):
            self.store.add_research_source({"title": "trust me", "url": "a blog somewhere"})

    def test_segment_is_unknown_without_screening_criteria(self):
        self.store.close()
        shutil.rmtree(self.d)
        self.d = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.d, "validation"), create=True)
        self.store.init_project("x", "y")
        self.seg = self.store.add_segment({"name": "Everyone", "definition": "anyone with a house"})
        self.evidence(self.claim("segment"), "D", {"extracts": self.interviewed(6)})
        d = self.level("segment")
        self.assertEqual(d["level"], "Unknown")
        self.assertIn("criteria", d["missing"][0])

    def full(self):
        """Fixture: moderate real evidence on all seven questions."""
        ids = self.interviewed(6, kind="spend")
        xid = self.experiment("preorder", dict(DESIGN, offer_terms="Refundable until delivery."))
        self.events(xid, "visit", 250, cost=300)
        self.events(xid, "demo_request", 20)
        for p in ("a", "b", "c"):
            self.pay(xid, p)
        for dim in ("problem", "segment"):
            self.evidence(self.claim(dim), "D", {"extracts": ids})
        for dim in ("demand", "behavior"):
            self.evidence(self.claim(dim), "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"})
        for dim in ("payment", "solution", "economics"):
            self.evidence(self.claim(dim), "G", {"experiment": xid})
        return xid

    def test_verdicts(self):
        self.assertEqual(score.verdict(score.dimensions(self.store))["decision"], "No recommendation yet")
        self.evidence(self.claim("problem"), "D", {"extracts": self.interviewed(5)})
        self.assertEqual(score.verdict(score.dimensions(self.store))["decision"], "No recommendation yet")
        xid = self.experiment()
        self.events(xid, "visit", 250)
        self.events(xid, "demo_request", 20)
        self.evidence(self.claim("demand"), "F", {"experiment": xid, "event": "demo_request", "denominator": "visit"})
        v = score.verdict(score.dimensions(self.store))
        self.assertEqual(v["decision"], "Conditional Go")
        self.assertIn("payment", v["conditions"])

    def test_go_needs_all_seven_and_a_contested_grade_blocks_it(self):
        self.full()
        self.assertEqual(score.verdict(score.dimensions(self.store))["decision"], "Go")
        against = self.interviewed(2, kind="statement", theme="no problem")
        self.evidence(self.claim("problem"), "D", {"extracts": against}, stance="contradicts")
        d = self.level("problem")
        self.assertEqual((d["level"], d["contested"], d["tier"], d["support_tier"]), ("Weakly supported", True, 1, 2))
        v = score.verdict(score.dimensions(self.store))
        self.assertEqual(v["decision"], "No recommendation yet")       # two real people saying no un-proves the problem
        self.assertIn("problem", v["conditions"])
        self.assertIn("held down", d["missing"][0])

    def test_the_next_step_is_the_riskiest_untested_assumption_cheapest_test_first(self):
        self.hypothesis("distribution", impact=2, uncertainty=2, cost=3, time=3)
        price = self.hypothesis("commercial", impact=5, uncertainty=5, cost=1, time=1, statement="Adjusters will pay 49 a month")
        r = score.recommend(self.store)
        self.assertEqual(r["hypothesis_id"], price)
        self.assertEqual(r["experiment"]["id"], "problem_interviews")      # problem unproven: no price test yet
        self.assertIn("Problem evidence is 'Unknown'", r["prerequisite"])
        self.assertIn("Do not pay for product development yet", r["do_not_build"])
        self.evidence(self.claim("problem"), "D", {"extracts": self.interviewed(5)})
        r = score.recommend(self.store)
        self.assertIsNone(r["prerequisite"])
        self.assertEqual(r["experiment"]["id"], "problem_interviews")      # first rung for a commercial question
        self.evidence(self.claim("payment", hypothesis_id=price), "D", {"extracts": self.interviewed(2, kind="statement")})
        self.assertEqual(score.recommend(self.store)["experiment"]["id"], "price_test")
        h = next(x for x in score.hypotheses(self.store) if x["id"] == price)
        self.assertEqual((h["status"], h["answered"], h["priority"]), ("Unknown", False, 25.0))   # talk cannot answer payment

    def test_a_hypothesis_explored_only_synthetically_is_still_unanswered(self):
        h = self.hypothesis()
        self.evidence(self.claim("problem", hypothesis_id=h), "B", {"run": self.lab()})
        got = score.hypotheses(self.store)[0]
        self.assertEqual((got["status"], got["answered"], got["explored_synthetically"], got["real_items"]),
                         ("Unknown", False, True, 0))


class Reporting(Grading):
    def test_the_report_has_every_section_and_links_conclusions_to_evidence(self):
        self.hypothesis()
        self.full()
        rid = self.lab()
        self.evidence(self.claim("demand"), "B", {"run": rid})
        text = fv_report.report(score.snapshot(self.store))
        for n, title in enumerate(("Executive summary", "Business concept", "Target customer", "Problem evidence",
                                   "Market research", "Synthetic customer insights", "Actual customer interviews",
                                   "Actual survey findings", "Behavioral experiments", "Pricing evidence",
                                   "Competitive environment", "Financial viability", "Contradictory evidence",
                                   "Critical unanswered questions", "Validation status", "Recommended next experiments",
                                   "Go / Conditional Go / No-Go"), 1):
            self.assertIn("## %d. %s" % (n, title), text)
        self.assertIn("**Recommendation: Go.**", text)
        self.assertIn("| Synthetic answers (SIMULATED) | 36 | none, at any number |", text)
        self.assertIn("deliberately no overall score", text)
        self.assertRegex(text, r"\| Is the problem real\? \| Moderately supported \| problem \[E\d+")
        synthetic = text.split("## 6. Synthetic customer insights")[1].split("## 7.")[0]
        self.assertIn("SIMULATED. Not customers", synthetic)
        self.assertIn("(simulated objection)", synthetic)
        self.assertNotIn("%", text.split("## 15. Validation status")[1].split("## 16.")[0])   # no falsely precise score
        self.assertIn("Summary by AI, not a quote", text)
        self.assertIn("hash chain intact", text)

    def test_an_empty_project_claims_nothing(self):
        text = fv_report.report(score.snapshot(self.store))
        self.assertIn("**Recommendation: No recommendation yet.**", text)
        self.assertIn("absence of testing, not absence of problems", text)
        self.assertNotIn("Strongly supported |", text)
        status = fv_report.status_text(score.snapshot(self.store))
        self.assertIn("0 people interviewed, 0 valid survey answers, 0 qualified actions on a primary metric, 0 paying customers", status)

    def test_the_dashboard_keeps_real_and_simulated_apart(self):
        self.full()
        self.lab()
        html = fv_dashboard.render(score.snapshot(self.store))
        data = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        snap = json.loads(data)
        self.assertEqual(snap["counts"]["synthetic_responses"], 36)
        self.assertEqual(snap["counts"]["paying_customers"], 3)
        self.assertEqual(snap["verdict"]["decision"], "Go")
        for needle in ('class="tag sim">SIMULATED', 'class="tag real">REAL', "carries no weight, at any number",
                       'data-f="segment"', 'data-f="category"', 'data-f="concept"', 'data-f="price"', 'data-f="from"'):
            self.assertIn(needle, html)
        self.assertNotIn("http", html.replace("https://example.org", ""))      # one file, nothing loaded from the network

    def test_export_keeps_the_four_data_families_in_separate_folders(self):
        self.full()
        self.lab()
        out = os.path.join(self.d, "export")
        fv_report.export(self.store, score.snapshot(self.store), out)
        self.assertEqual(sorted(os.listdir(out)), ["behaviour", "real_respondents", "record", "snapshot.json", "synthetic",
                                                   "transactions", "validation-report.md"])
        self.assertEqual(sorted(os.listdir(os.path.join(out, "synthetic"))),
                         ["syn_personas.csv", "syn_responses.csv", "syn_runs.csv"])
        self.assertEqual(os.listdir(os.path.join(out, "transactions")), ["transactions.csv"])
        with open(os.path.join(out, "transactions", "transactions.csv")) as fh:
            self.assertEqual(len(list(csv.reader(fh))), 4)


class Documentation(unittest.TestCase):
    """The examples in the reference guides must be accepted by the tool they document."""

    def read(self, name):
        here = os.path.dirname(os.path.abspath(validate.__file__))
        with open(os.path.join(here, "references", name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_interview_guides_pass_their_own_linter(self):
        text = self.read("interviews.md")
        for number, guide_type in enumerate(("problem_discovery", "solution_testing", "pricing", "purchasing", "post_purchase"), 1):
            section = text.split("### %d." % number)[1].split("###")[0].split("\n## ")[0]
            bullets = "\n".join(l for l in section.splitlines() if l.startswith(("- ", "  ")))
            res = research.lint_guide(bullets, guide_type)
            self.assertGreaterEqual(res["questions"], 4, guide_type)
            self.assertEqual(res["flags"], [], guide_type)
        problem = text.split("### 1.")[1].split("###")[0]
        self.assertIn("hypothetical", [f["rule"] for f in research.lint_guide(problem)["flags"]])   # the counter-example

    def test_the_survey_and_experiment_examples_are_valid(self):
        inst = json.loads(self.read("surveys.md").split("```json\n")[1].split("```")[0])
        self.assertEqual(research.validate_instrument(inst), ([], []))
        design = json.loads(self.read("experiments.md").split("```json\n")[1].split("```")[0])
        self.assertEqual(experiments.validate_design(design["type"], design["design"]), [])

    def test_the_evidence_guide_matches_the_grading_rules(self):
        text = self.read("evidence.md")
        for cat, row in (("D", "| D: interviewed people | 1 | 5 describing past behaviour or spend | 10 |"),
                         ("E", "| E: valid survey answers | 1 | 30 to a past-behaviour question | 100 |"),
                         ("F", "| F: qualified observed actions | 1 | 10 | 30 |"), ("G", "| G: paying customers, net | 1 | 3 | 10 |")):
            self.assertIn(row, text)
            self.assertEqual([int(x) for x in __import__("re").findall(r"\| (\d+)", row)], list(score.THRESHOLDS[cat]))
        names = {0: "no", 1: "weak", 2: "moderate", 3: "strong"}
        for dim, caps in score.CAPS.items():
            row = "| %s | %s |" % (dim, " | ".join(names[caps.get(c, 0)] for c in "CDEFG"))
            self.assertIn(row, text)


class CommandLine(unittest.TestCase):
    def setUp(self):
        os.environ["FOUNDER_VALIDATE_NOW"] = CLOCK
        self.d = tempfile.mkdtemp()
        self.dir = os.path.join(self.d, "founder", "validation")
        self.lines = []

    def tearDown(self):
        shutil.rmtree(self.d)
        os.environ.pop("FOUNDER_VALIDATE_NOW", None)

    def run_cli(self, *args, **kw):
        if "json" in kw:
            path = os.path.join(self.d, "in.json")
            with open(path, "w") as fh:
                json.dump(kw["json"], fh)
            args = args + ("--json", path)
        return validate.main(["--dir", self.dir] + list(args), out=self.lines.append)

    def test_the_guided_flow_end_to_end(self):
        idea = os.path.join(self.d, "idea.md")
        with open(idea, "w") as fh:
            fh.write("# Fixture Co\n\nDraft inspection reports from recordings.\n")
        self.assertEqual(self.run_cli("init", "--idea", idea), 0)
        self.assertEqual(self.run_cli("init", "--idea", idea), 2)                       # one idea per record
        self.run_cli("add", "segment", json={"name": "Solo adjuster", "definition": "d", "criteria": "20+ reports a month"})
        self.run_cli("add", "hypothesis", json=[
            {"area": "problem", "statement": "Adjusters lose hours per report", "impact": 5, "uncertainty": 4, "test_cost": 1, "test_time": 2},
            {"area": "commercial", "statement": "They pay 49 a month", "impact": 5, "uncertainty": 5, "test_cost": 2, "test_time": 3}])
        self.assertEqual(self.run_cli("next"), 0)
        self.assertIn("Problem-discovery interviews", "\n".join(self.lines))
        with open(os.path.join(self.d, "c.json"), "w") as fh:
            json.dump(CUSTOMER, fh)
        with open(os.path.join(self.d, "arms.json"), "w") as fh:
            json.dump(ARMS, fh)
        self.assertEqual(self.run_cli("synth", "init", "--customer", os.path.join(self.d, "c.json"), "--arms",
                                      os.path.join(self.d, "arms.json"), "--n", "10", "--seed", "2", "--model", "fixture-model"), 0)
        self.assertEqual(self.run_cli("synth", "briefs", "R001", "--stage", "problem"), 0)
        self.assertIn("never answer one yourself", "\n".join(self.lines))
        self.assertEqual(self.run_cli("synth", "tally", "R001"), 2)                     # nothing answered: nothing to tally
        self.run_cli("add", "participant", json={"segment_id": "SEG001", "consent": "recorded", "consent_scope": "quotes"})
        t = os.path.join(self.d, "t.txt")
        with open(t, "w") as fh:
            fh.write("P: I paid a temp four hundred dollars last month to type them up.\n")
        self.run_cli("add", "interview", json={"participant_id": "PT001", "guide_type": "problem_discovery",
                                               "conducted_on": "2026-10-02", "record_kind": "transcript", "record_path": t})
        self.assertEqual(self.run_cli("add", "extract", json={"interview_id": "IV001", "kind": "spend", "verbatim": True,
                                                              "text": "I paid a temp four hundred dollars last month", "amount": 400,
                                                              "currency": "USD", "theme": "typing cost"}), 0)
        self.assertEqual(self.run_cli("add", "extract", json={"interview_id": "IV001", "kind": "statement", "verbatim": True,
                                                              "text": "I would definitely buy this"}), 2)
        self.run_cli("add", "claim", json={"description": "Adjusters already pay to get reports typed", "dimension": "problem",
                                           "hypothesis_id": "H001", "segment_id": "SEG001"})
        self.assertEqual(self.run_cli("add", "evidence", json={"claim_id": "C001", "stance": "supports", "category": "D",
                                                               "ref": {"extracts": [1]}, "summary": "One adjuster paid a temp"}), 0)
        self.assertEqual(self.run_cli("experiment", "register", json={"type": "landing_page", "title": "Demo page",
                                                                      "design": DESIGN, "hypothesis_id": "H002"}), 0)
        self.assertEqual(self.run_cli("experiment", "launch", "X001", "--on", "2026-10-03"), 0)
        events = os.path.join(self.d, "events.csv")
        with open(events, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["occurred_on", "event", "count", "qualified", "traffic_source", "cost"])
            w.writerows([["2026-10-04", "visit", 250, "yes", "newsletter", 300], ["2026-10-04", "demo_request", 20, "yes", "newsletter", 0],
                         ["2026-10-05", "visit", 900, "", "social", 0]])
        self.assertEqual(self.run_cli("experiment", "import", "X001", "--csv", events), 0)
        self.assertEqual(self.run_cli("experiment", "import", "X001", "--csv", events), 2)   # the same export twice
        del self.lines[:]
        self.assertEqual(self.run_cli("experiment", "read", "X001"), 0)
        self.assertIn("8.0% (20 of 250; 95% interval 5.2% to 12.0%); left out: 0 unqualified, 900 unknown", "\n".join(self.lines))
        for cmd in ("status", "hypotheses", "pricing", "calibration", "report", "dashboard", "export", "audit"):
            self.assertEqual(self.run_cli(cmd), 0, cmd)
        out = "\n".join(self.lines)
        self.assertIn("hash chain intact", out)
        self.assertIn("What interviewed customers already spend", out)
        for name in ("validation-report.md", "dashboard.html", "validation.db"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, name)), name)
        with open(os.path.join(self.dir, "validation-report.md"), encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn('Verbatim, PT001 (spend, extract 1): "I paid a temp four hundred dollars last month"', report)
        self.assertIn("No recommendation yet", report)

    def test_wrong_shaped_input_is_a_clean_error_and_saves_nothing(self):
        validate.main(["--dir", self.dir, "init", "--name", "x", "--concept", "y"], out=self.lines.append)
        for kind, payload in (("evidence", "just a string"), ("participant", [1, 2]), ("transaction", "x"),
                              ("claim", {"description": 5, "dimension": "problem"}), ("hypothesis", [[1]])):
            self.assertEqual(self.run_cli("add", kind, json=payload), 2, kind)
        self.assertEqual(self.run_cli("survey", "exclude", "abc", "--reason", "r"), 2)
        self.assertEqual(self.run_cli("void", "event", "abc", "--reason", "r"), 2)
        self.assertEqual(self.run_cli("recruit", json=["SEG001"]), 2)
        self.assertEqual(self.run_cli("status"), 0)

    def test_plan_sample_and_guide_lint(self):
        validate.main(["--dir", self.dir, "init", "--name", "x", "--concept", "y"], out=self.lines.append)
        self.assertEqual(self.run_cli("experiment", "plan-sample", "--type", "ab_test", "--baseline", "0.05", "--min-effect", "0.02"), 0)
        self.assertIn("qualified observations in each version", self.lines[-1])
        guide = os.path.join(self.d, "g.md")
        with open(guide, "w") as fh:
            fh.write("- Would you use this?\n- When did you last do it?\n")
        self.assertEqual(self.run_cli("guide", "lint", guide), 1)


if __name__ == "__main__":
    unittest.main()
