#!/usr/bin/env python3
"""The market validation engine for founder-validate. Standard library only, no network.

Keeps one evidence record per business idea and answers five questions from it:
is the problem real, do the right customers want this, will they pay, can it be
done profitably, and what is the cheapest next experiment. It separates what you
assume, what AI predicts, what research indicates, what customers say, what they
do and what they pay for, and it never lets one pass for another.

    python3 validate.py init --idea founder/idea.md
    python3 validate.py add hypothesis --json hypotheses.json     # also: segment, claim, evidence, research,
                                                                  # participant, interview, extract, transaction,
                                                                  # prediction, outcome, concept
    python3 validate.py next                                      # the most important unanswered question
    python3 validate.py synth init --customer c.json --arms arms.json --model <model id> [--n 100]
    python3 validate.py synth briefs R001 --stage problem         # then concept; one sub-agent per brief
    python3 validate.py synth ingest R001 && python3 validate.py synth tally R001
    python3 validate.py guide lint guide.md --type problem_discovery
    python3 validate.py survey create --json survey.json && python3 validate.py survey import SV001 --csv answers.csv
    python3 validate.py experiment register --json design.json && python3 validate.py experiment launch X001
    python3 validate.py experiment import X001 --csv events.csv && python3 validate.py experiment read X001
    python3 validate.py status | report | dashboard | export | audit

State lives in founder/validation/ (--dir to change it): validation.db, records/,
synth/, validation-report.md, dashboard.html. JSON input comes from --json FILE
or standard input, as one object or a list of objects.

The tool never invents a respondent, a quote, a visitor or a payment. Every row
is something you imported, and every row says where it came from.
"""

import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fv_dashboard as dashboard  # noqa: E402
import fv_experiments as experiments  # noqa: E402
import fv_report as reporting  # noqa: E402
import fv_research as research  # noqa: E402
import fv_score as score  # noqa: E402
import fv_stats as stats  # noqa: E402
import fv_synth as synth  # noqa: E402
from fv_store import GUIDE_TYPES, Store, StoreError  # noqa: E402


def _sibling(folder, name):
    path = os.path.join(HERE, "..", folder, name + ".py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("founder_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_numbers(directory):
    """The CFO's projection, if founder/numbers.json sits beside the validation folder. Optional."""
    path = os.path.join(os.path.dirname(os.path.abspath(directory)), "numbers.json")
    ue = _sibling("founder-cfo", "unit_economics")
    if ue is None or not os.path.exists(path):
        return None
    try:
        return ue.analyse(ue.load(path))
    except Exception:
        return None


def snapshot(store):
    return score.snapshot(store, load_numbers(store.dir), _sibling("founder-pricing", "van_westendorp"))


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        raise StoreError("no such file: %s" % path)


def read_json(path):
    try:
        return json.loads(sys.stdin.read() if path in (None, "-") else read_text(path))
    except json.JSONDecodeError as e:
        raise StoreError("the input is not valid JSON: %s" % e)


def as_list(obj):
    return obj if isinstance(obj, list) else [obj]


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


ADDERS = {
    "concept": lambda s, o: s.add_concept(o),
    "segment": lambda s, o: s.add_segment(o),
    "hypothesis": lambda s, o: s.add_hypothesis(o),
    "claim": lambda s, o: s.add_claim(o),
    "evidence": lambda s, o: s.add_evidence(o),
    "research": lambda s, o: s.add_research_source(o),
    "participant": lambda s, o: research.add_participant(s, o),
    "interview": lambda s, o: research.add_interview(s, o),
    "extract": lambda s, o: research.add_extract(s, o),
    "transaction": lambda s, o: experiments.add_transaction(s, o),
    "prediction": lambda s, o: score.add_prediction(s, o),
    "outcome": lambda s, o: score.add_outcome(s, o),
}


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join("founder", "validation"))
    ap.add_argument("--actor", help="who is making this change, for the audit trail (default: founder)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="start the evidence record for one business idea")
    p.add_argument("--name")
    p.add_argument("--concept")
    p.add_argument("--idea", help="founder/idea.md: first heading is the name, the rest the concept")
    p.add_argument("--price", type=float)
    p.add_argument("--currency")

    p = sub.add_parser("add", help="add records from JSON")
    p.add_argument("kind", choices=sorted(ADDERS))
    p.add_argument("--json", dest="json_path")

    p = sub.add_parser("hypothesis", help="revise or retire a hypothesis (old versions are kept)")
    p.add_argument("action", choices=["revise", "retire", "history"])
    p.add_argument("id")
    p.add_argument("--json", dest="json_path")
    p.add_argument("--reason")

    p = sub.add_parser("retract", help="retract an evidence item; it stays in the record")
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    p = sub.add_parser("participant", help="update or redact a participant")
    p.add_argument("action", choices=["update", "redact"])
    p.add_argument("id")
    p.add_argument("--json", dest="json_path")
    p.add_argument("--reason")

    p = sub.add_parser("recruit", help="set interview targets per segment: --json {\"SEG001\": 10}")
    p.add_argument("--json", dest="json_path")

    p = sub.add_parser("guide", help="lint an interview guide for leading and hypothetical questions")
    p.add_argument("action", choices=["lint"])
    p.add_argument("file")
    p.add_argument("--type", default="problem_discovery", choices=list(GUIDE_TYPES))

    p = sub.add_parser("survey", help="create, print, import, exclude, show")
    p.add_argument("action", choices=["create", "form", "import", "exclude", "show"])
    p.add_argument("id", nargs="?")
    p.add_argument("--json", dest="json_path")
    p.add_argument("--csv")
    p.add_argument("--out")
    p.add_argument("--via")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--reason")

    p = sub.add_parser("synth", help="the synthetic customer lab (simulated, never evidence)")
    p.add_argument("action", choices=["init", "briefs", "ingest", "tally", "import-panel", "predict"])
    p.add_argument("id", nargs="?")
    p.add_argument("--customer")
    p.add_argument("--arms")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int)
    p.add_argument("--model")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--assumptions", default="")
    p.add_argument("--stage", choices=list(synth.STAGES))
    p.add_argument("--wave", type=int, default=10)
    p.add_argument("--arm")
    p.add_argument("--segment", help="segment id the prediction is about (synth predict)")
    p.add_argument("--panel-dir", default=os.path.join("founder", "panel"))

    p = sub.add_parser("experiment", help="register, launch, amend, record, import, read, complete, plan-sample")
    p.add_argument("action", choices=["register", "launch", "amend", "record", "import", "read", "complete", "abandon", "plan-sample"])
    p.add_argument("id", nargs="?")
    p.add_argument("--json", dest="json_path")
    p.add_argument("--csv")
    p.add_argument("--on")
    p.add_argument("--change")
    p.add_argument("--reason")
    p.add_argument("--conclusion")
    p.add_argument("--type", default="landing_page")
    p.add_argument("--baseline", type=float)
    p.add_argument("--min-effect", type=float)
    p.add_argument("--margin", type=float)

    p = sub.add_parser("void", help="void an event or a transaction recorded in error; it stays in the record")
    p.add_argument("what", choices=["event", "transaction"])
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    for name, helptext in (("status", "the seven grades and the next step"), ("next", "the most important unanswered question"),
                           ("hypotheses", "every hypothesis by priority"), ("pricing", "the six layers of price evidence"),
                           ("calibration", "predictions set against real results"), ("audit", "verify the audit trail")):
        sub.add_parser(name, help=helptext)
    for name in ("report", "dashboard", "export"):
        p = sub.add_parser(name)
        p.add_argument("--out")
    return ap


def run(a, out):
    if a.cmd == "init":
        name, concept = a.name, a.concept
        if a.idea:
            text = read_text(a.idea).strip()
            lines = text.splitlines()
            if lines and lines[0].startswith("# "):
                name, concept = name or lines[0][2:].strip(), concept or "\n".join(lines[1:]).strip()
            else:
                concept = concept or text
        store = Store(a.dir, create=True, actor=a.actor)
        try:
            cid = store.init_project(name or "", concept or "", a.price, a.currency)
            out("started the evidence record for %r in %s (concept %s). Next: add segments and hypotheses." % (
                store.meta("project_name"), a.dir, cid))
        finally:
            store.close()
        return 0

    store = Store(a.dir, actor=a.actor)
    try:
        code = dispatch(store, a, out)
        store.commit()
        return code
    finally:
        store.close()


def dispatch(store, a, out):
    if a.cmd == "add":
        ids = [ADDERS[a.kind](store, o) for o in as_list(read_json(a.json_path))]
        out("added %d %s: %s" % (len(ids), a.kind, ", ".join(str(i) for i in ids)))
    elif a.cmd == "hypothesis":
        if a.action == "revise":
            v = store.revise_hypothesis(a.id, read_json(a.json_path), a.reason)
            out("%s is now version %d; earlier versions are kept" % (a.id, v))
        elif a.action == "retire":
            store.retire_hypothesis(a.id, a.reason)
            out("retired %s" % a.id)
        else:
            for v in store.rows("SELECT * FROM hypothesis_versions WHERE hypothesis_id = ? ORDER BY version", (a.id,)):
                out("v%d %s (%s): %s [impact %d, uncertainty %d]" % (v["version"], v["changed_at"][:10], v["reason"],
                                                                    v["statement"], v["impact"], v["uncertainty"]))
    elif a.cmd == "retract":
        store.retract_evidence(a.id, a.reason)
        out("retracted %s; it stays listed under contradictory and retracted evidence" % a.id)
    elif a.cmd == "participant":
        if a.action == "update":
            research.update_participant(store, a.id, read_json(a.json_path))
            out("updated %s" % a.id)
        else:
            research.redact_participant(store, a.id, a.reason)
            out("redacted %s: their words and stored records are removed and no longer counted" % a.id)
    elif a.cmd == "recruit":
        targets = read_json(a.json_path)
        for sid in targets:
            store.get("segments", sid, "segment")
        store.set_meta("recruit_targets", json.dumps(targets, sort_keys=True))
        out("targets set. Progress is counted from participant records only.")
    elif a.cmd == "guide":
        res = research.lint_guide(read_text(a.file), a.type)
        out("%d questions, %d flagged. %s about past behaviour." % (
            res["questions"], len(res["flags"]), stats.pct(res["past_share"], 0) if res["past_share"] is not None else "none"))
        for f in res["flags"]:
            out("line %d [%s] %s\n    %s" % (f["line"], f["rule"], f["question"], f["message"]))
        if res["past_share"] is not None and res["past_share"] < 0.5 and a.type == "problem_discovery":
            out("Fewer than half the questions ask about something that already happened. Rewrite toward the last time.")
        return 1 if res["flags"] else 0
    elif a.cmd == "survey":
        return survey_cmd(store, a, out)
    elif a.cmd == "synth":
        return synth_cmd(store, a, out)
    elif a.cmd == "experiment":
        return experiment_cmd(store, a, out)
    elif a.cmd == "void":
        if a.what == "event":
            experiments.void_event(store, int(a.id), a.reason)
        else:
            experiments.void_transaction(store, a.id, a.reason)
        out("voided %s %s" % (a.what, a.id))
    elif a.cmd == "status":
        out(reporting.status_text(snapshot(store)).rstrip())
    elif a.cmd == "next":
        r = score.recommend(store)
        if not r.get("question"):
            out(r["note"])
        else:
            e = r["experiment"]
            out("Most important unanswered question (%s, priority %.1f):\n  %s\n  %s" % (r["hypothesis_id"], r["priority"], r["question"], r["why"]))
            if r.get("prerequisite"):
                out("First: %s" % r["prerequisite"])
            out("Cheapest credible experiment: %s\n  who: %s\n  how: %s\n  metric: %s\n  stop: %s\n  cost: %s, about %s days" % (
                e["name"], e["population"], e["method"], e["metric"], e["stop"], e["cost"], e["days"]))
            for k in ("supports", "contradicts", "unclear"):
                out("  if it %s: %s" % (k if k != "unclear" else "is unclear", e["outcomes"][k]))
            if r.get("do_not_build"):
                out(r["do_not_build"])
    elif a.cmd == "hypotheses":
        for h in score.hypotheses(store):
            out("%s %-12s priority %5.1f  %-24s %s%s" % (h["id"], h["area"], h["priority"], h["status"], h["statement"],
                                                       "  (synthetic exploration only)" if h["explored_synthetically"] and not h["real_items"] else ""))
    elif a.cmd == "pricing":
        p = score.pricing(store, _sibling("founder-pricing", "van_westendorp"))
        if not p["layers"]:
            out("No price evidence yet.")
        for layer in p["layers"]:
            out("%d. %s [%s]%s\n   %s" % (layer["layer"], layer["name"], layer["category"],
                                         " SIMULATED" if layer["category"] == "B" else "", reporting._price_line(layer)))
        if p["role_gap"]:
            out("Not yet interviewed: %s." % ", ".join(p["role_gap"]))
        out("Strongest layer reached: %d of 6. Layers are never averaged." % p["highest_layer"])
    elif a.cmd == "calibration":
        c = score.calibration(store)
        out(c["statement"])
        for pr in c["pairs"]:
            out("%s vs %s: predicted %s (%s), actual %s. %s" % (
                pr["prediction_id"], pr["experiment_id"], stats.pct(pr["predicted"]), pr["predicted_measure"],
                stats.describe_rate(pr["actual_k"], pr["actual_n"]) if pr["actual"] is not None else "unreadable",
                "comparable" if pr["comparable"] else "NOT comparable: " + pr["comparable_note"]))
            for r in pr["possible_reasons"]:
                out("    - %s" % r)
        for row in c["summary"]:
            out("%s / %s / %s: %s" % (row["source"], row["model"] or "no model", row["prediction_type"], row["says"]))
    elif a.cmd == "audit":
        ok, n, bad = store.verify_audit()
        out("audit trail: %d entries, %s" % (n, "hash chain intact" if ok else "BROKEN at entry %s" % bad))
        return 0 if ok else 1
    elif a.cmd == "report":
        path = a.out or os.path.join(store.dir, "validation-report.md")
        snap = snapshot(store)
        write(path, reporting.report(snap))
        out("%s. Wrote %s" % (snap["verdict"]["decision"], path))
    elif a.cmd == "dashboard":
        path = a.out or os.path.join(store.dir, "dashboard.html")
        write(path, dashboard.render(snapshot(store)))
        out("wrote %s (one self-contained file; open it in a browser)" % path)
    elif a.cmd == "export":
        path = a.out or os.path.join(store.dir, "export")
        n = reporting.export(store, snapshot(store), path)
        out("exported %d files to %s. They contain what participants said: share with care." % (n, path))
    return 0


def survey_cmd(store, a, out):
    if a.action == "create":
        sid, warnings = research.create_survey(store, read_json(a.json_path), {"distributed_via": a.via or ""})
        out("created %s" % sid)
        for w in warnings:
            out("warning: %s" % w)
    elif a.action == "form":
        inst = json.loads(store.get("surveys", a.id, "survey")["instrument_json"])
        text, header = research.survey_form(inst)
        if a.out:
            write(a.out, text)
            out("wrote %s. Build it in your survey tool, collect answers, then: survey import %s --csv <export>" % (a.out, a.id))
        else:
            out(text)
    elif a.action == "import":
        if not a.csv:
            raise StoreError("give the exported answers with --csv")
        r = research.import_responses(store, a.id, a.csv, a.date_from, a.date_to, a.via)
        out("read %d rows: %d valid, %d excluded (%s). Excluded rows are kept with their reason." % (
            r["read"], r["valid"], r["read"] - r["valid"], reporting._kv(r["excluded"]) or "none"))
        for w in r["warnings"]:
            out("warning: %s" % w)
    elif a.action == "exclude":
        research.exclude_response(store, int(a.id), a.reason)
        out("excluded response %s" % a.id)
    else:
        s = research.analyse_survey(store, a.id)
        out("%s: %d received, %d valid, excluded: %s\n%s" % (s["title"], s["received"], s["valid"],
                                                           reporting._kv(s["excluded"]) or "none", s["representative"]))
        for q in s["questions"]:
            if q["type"] in ("single", "multi"):
                out("[%s] %s (n = %d)" % (q["kind"], q["text"], q["n"]))
                for o in q["options"]:
                    out("    %s: %s" % (o["option"], stats.describe_rate(o["k"], q["n"])))
            elif q["type"] == "number":
                out("[%s] %s (n = %d): median %s" % (q["kind"], q["text"], q["n"], q.get("median")))
    return 0


def synth_cmd(store, a, out):
    if a.action == "init":
        if not a.customer or not a.arms:
            raise StoreError("synth init needs --customer and --arms")
        rid = synth.init_run(store, read_json(a.customer), as_list(read_json(a.arms)), a.n, a.seed, a.model, a.repeats, a.assumptions)
        run = store.get("syn_runs", rid)
        out("run %s: dealt %d simulated profiles (seed %s, %d repeat(s)). Next: synth briefs %s --stage problem" % (
            rid, run["n_personas"], run["seed"], run["repeats"], rid))
    elif a.action == "briefs":
        if not a.stage:
            raise StoreError("say which stage: --stage problem (no solution shown) or --stage concept")
        waves = synth.write_briefs(store, a.id, a.stage, a.wave)
        n = sum(len(w) for w in waves)
        if not n:
            out("every profile has a valid %s answer. Next: synth ingest %s" % (a.stage, a.id))
        else:
            out("%d briefs in %d waves of up to %d. One sub-agent per brief; never answer one yourself:" % (n, len(waves), a.wave))
            for k, w in enumerate(waves, 1):
                out("wave %d: %s" % (k, " ".join("%s.r%d=%s" % job for job in w)))
    elif a.action == "ingest":
        filed, problems = synth.ingest(store, a.id)
        out("filed %d simulated answers into the synthetic tables" % filed)
        for pid, stage, rep, prob in problems:
            out("%s %s r%d: %s" % (pid, stage, rep, prob))
        return 1 if problems else 0
    elif a.action == "tally":
        res = synth.tally(store, a.id)
        d = synth.run_dir(store, a.id)
        write(os.path.join(d, "results.md"), synth.results_md(res))
        write(os.path.join(d, "results.json"), json.dumps(reporting.clean(res), indent=1, ensure_ascii=False))
        out("SIMULATED, not customers. %d questions for real customers, %d hypotheses to test. Wrote %s" % (
            len(res["questions_for_real_customers"]), len(res["hypotheses_to_test"]), os.path.join(d, "results.md")))
    elif a.action == "import-panel":
        rid, filed = synth.import_panel(store, a.panel_dir, a.model or "not recorded")
        out("imported the founder-consumer panel as synthetic run %s (%d simulated answers)" % (rid, filed))
    elif a.action == "predict":
        pid = score.predict_from_run(store, a.id, a.arm, a.segment)
        out("recorded %s: the simulated stance share, frozen now so a real result can be set against it later" % pid)
    return 0


def experiment_cmd(store, a, out):
    if a.action == "plan-sample":
        if a.baseline is None:
            raise StoreError("plan-sample needs --baseline (your best guess of the rate) and --min-effect or --margin")
        try:
            out(experiments.plan_sample(a.type, a.baseline, a.min_effect, a.margin)["says"])
        except (stats.StatsError, TypeError) as e:
            raise StoreError("cannot plan a sample: %s" % e)
    elif a.action == "register":
        xid = experiments.register(store, read_json(a.json_path))
        out("registered %s. The design is on the record; it locks at launch." % xid)
    elif a.action == "launch":
        experiments.launch(store, a.id, a.on)
        out("%s is running. From now the design can only be amended, with a reason." % a.id)
    elif a.action == "amend":
        experiments.amend(store, a.id, a.change, a.reason)
        out("amendment recorded on %s" % a.id)
    elif a.action == "record":
        ids = experiments.record_events(store, a.id, as_list(read_json(a.json_path)))
        out("recorded %d event rows on %s" % (len(ids), a.id))
    elif a.action == "import":
        ids = experiments.import_events_csv(store, a.id, a.csv or "")
        out("imported %d event rows into %s" % (len(ids), a.id))
    elif a.action == "read":
        r = experiments.read(store, a.id)
        out("%s: %s (%s)%s" % (r["id"], r["title"], r["status"], ", INTERIM look %d" % r["looks"] if r["interim"] else ""))
        for arm in r["arms"]:
            out("  %s%s: %s; left out: %d unqualified, %d unknown" % (
                arm["variant"], (" at %s" % arm["price_point"]) if arm["price_point"] is not None else "",
                stats.describe_rate(arm["k"], arm["n"]) if arm["k"] <= arm["n"] else "inconsistent", arm["unqualified_n"], arm["unknown_n"]))
        out("  outcome: %s. %s" % (r["outcome"].replace("_", " "), r["reading"]))
        if r["meaning"]:
            out("  you said in advance this would mean: %s" % r["meaning"])
        if r["money"]["transactions"]:
            out("  money: %d paying customer(s) net, %d cancelled or refunded" % (r["money"]["n_payers"], len(r["money"]["cancelled_or_refunded"])))
    else:
        experiments.complete(store, a.id, a.conclusion, abandoned=a.action == "abandon")
        out("%s closed. Now attach its result to a claim as evidence (add evidence), for or against." % a.id)
    return 0


def main(argv=None, out=None):
    out = out or (lambda s: print(s))
    a = build_parser().parse_args(argv)
    try:
        return run(a, out)
    except (StoreError, stats.StatsError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
