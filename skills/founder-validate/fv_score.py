"""Evidence grading for founder-validate. Standard library only. Reads the store, writes nothing.

There is no validation score. There are seven separate questions, each graded on
a five-step scale from the real evidence behind it:

    Unknown / Weakly supported / Moderately supported / Strongly supported /
    Contradicted by evidence

The grade is computed. It cannot be typed in. The rules, all in this file:

  1. Categories A (assumptions) and B (synthetic responses) carry no weight.
     A thousand simulated answers grade exactly like none.
  2. Each evidence item is resolved to real units, counted from the underlying
     table at read time: distinct interviewed people, valid survey answers,
     qualified observed actions, distinct net payers. Never the number typed
     into a summary.
  3. What people SAY about the future is capped at "weak": interview opinions,
     and survey questions marked stated or pricing. Only reported past
     behaviour, observed behaviour and payment can go higher.
  4. Each question only accepts the categories that can answer it. Payment
     evidence is transactions and nothing else.
  5. Contradicting evidence is graded the same way and set against the support.
     It is never dropped.

The thresholds (THRESHOLDS below) are conventions chosen to be cautious for an
early-stage founder. They are not statistical laws, and the report says so.
"""

import json

import fv_experiments as experiments
import fv_research as research
import fv_stats as stats
import fv_synth as synth
from fv_store import CATEGORIES, DIMENSIONS, KNOWLEDGE, PAST_BEHAVIOUR_KINDS, REAL, StoreError, now

RULES_VERSION = "grading-1"
LEVELS = ["Unknown", "Weakly supported", "Moderately supported", "Strongly supported"]
CONTRADICTED = "Contradicted by evidence"
# Real units needed for (weak, moderate, strong), per category.
THRESHOLDS = {"C": (1, None, None), "D": (1, 5, 10), "E": (1, 30, 100), "F": (1, 10, 30), "G": (1, 3, 10)}
UNIT_NAMES = {"C": "independent sources", "D": "interviewed people describing past behaviour",
              "E": "valid survey answers about past behaviour", "F": "qualified observed actions", "G": "paying customers"}
# The highest tier each category can reach for each question (missing = cannot answer it at all).
CAPS = {
    "problem":   {"C": 1, "D": 3, "E": 3, "F": 3, "G": 3},
    "solution":  {"D": 2, "E": 1, "F": 3, "G": 3},
    "demand":    {"C": 1, "D": 1, "E": 1, "F": 3, "G": 3},
    "behavior":  {"F": 3, "G": 3},
    "payment":   {"G": 3},
    "segment":   {"C": 1, "D": 2, "E": 3, "F": 3, "G": 3},
    "economics": {"C": 1, "D": 1, "F": 2, "G": 3},
}
GENERIC_CAPS = {"C": 1, "D": 3, "E": 3, "F": 3, "G": 3}
QUESTIONS = {
    "problem": "Is there documented evidence that customers experience the problem?",
    "solution": "Have actual customers tested the proposed solution?",
    "demand": "Have qualified customers demonstrated meaningful interest?",
    "behavior": "Have customers taken concrete actions?",
    "payment": "Have customers paid or made genuine commercial commitments?",
    "segment": "Is the target customer sufficiently defined?",
    "economics": "Can the business deliver the solution profitably?",
}
WHY_NOT = {
    "solution": "Desk research cannot show that YOUR solution works; only people who tried it can.",
    "demand": "Interviews and surveys record stated interest, which is capped at weak. Qualified actions and payments count.",
    "behavior": "Only observed actions and payments count here. What people say they would do does not.",
    "payment": "Only recorded transactions count here: deposits, payments, signed contracts, net of refunds.",
    "economics": "Projections in numbers.json are assumptions. Measured acquisition cost, delivery cost and prices paid count.",
}


def resolve(store, e):
    """Turn one evidence row into real units, counted from the underlying tables now."""
    ref = json.loads(e["ref_json"])
    cat = e["category"]
    out = {"category": cat, "units": 0, "strong_units": 0, "keys": set(), "strong_keys": set(), "detail": "", "pool": None}
    if cat == "A":
        out["detail"] = "assumption, no data"
    elif cat == "B":
        run = store.get("syn_runs", ref["run"])
        out["detail"] = "%d simulated profiles (%s): counts for nothing" % (run["n_personas"], run["model"])
    elif cat == "C":
        out["keys"] = out["strong_keys"] = {"SRC:" + s for s in ref["sources"]}
        out["detail"] = "%d source(s)" % len(ref["sources"])
    elif cat == "D":
        rows = store.rows(
            "SELECT x.kind, i.participant_id FROM interview_extracts x JOIN interviews i ON i.id = x.interview_id"
            " JOIN participants p ON p.id = i.participant_id WHERE x.id IN (%s) AND x.redacted_at IS NULL"
            " AND p.redacted_at IS NULL" % ", ".join("?" * len(ref["extracts"])), list(ref["extracts"]))
        out["keys"] = {r["participant_id"] for r in rows}
        out["strong_keys"] = {r["participant_id"] for r in rows if r["kind"] in PAST_BEHAVIOUR_KINDS}
        out["detail"] = "%d interviewed people, %d of them describing past behaviour or spend" % (
            len(out["keys"]), len(out["strong_keys"]))
    elif cat == "E":
        sv = store.get("surveys", ref["survey"])
        q = next(x for x in json.loads(sv["instrument_json"])["questions"] if x["id"] == ref["question"])
        k, n = research.count_matching(store, ref["survey"], ref["question"], ref["match"], ref.get("among"))
        out["pool"] = ("E", ref["survey"])
        out["units"] = k
        out["strong_units"] = k if q["kind"] in ("behavioral", "screening") else 0
        out["k"], out["n"] = k, n
        out["detail"] = "%d of %d valid answers to a %s question" % (k, n, {
            "behavioral": "past-behaviour", "screening": "screening", "stated": "stated-preference",
            "pricing": "stated-price"}.get(q["kind"], q["kind"]))
    elif cat == "F":
        c = experiments.counts(store, ref["experiment"], ref["event"], ref.get("denominator") or ref["event"], ref.get("variant"))
        out["pool"] = ("F", ref["experiment"], ref["event"])
        out["units"] = out["strong_units"] = c["k"]
        out["k"], out["n"] = c["k"], (c["n"] if ref.get("denominator") else None)
        left = c["unqualified_k"] + c["unknown_k"]
        out["detail"] = "%d qualified '%s'%s%s" % (
            c["k"], ref["event"], (" of %d qualified '%s'" % (c["n"], ref["denominator"])) if ref.get("denominator") else "",
            (" (%d more not counted: unqualified or unknown)" % left) if left else "")
    elif cat == "G":
        m = experiments.money(store, experiment_id=ref.get("experiment"), ids=ref.get("transactions"))
        out["keys"] = out["strong_keys"] = {"PAY:" + p for p in m["payers"]}
        out["detail"] = "%d paying customer(s) net of refunds and cancellations" % m["n_payers"]
        if m["cancelled_or_refunded"]:
            out["detail"] += ", %d cancelled or refunded" % len(m["cancelled_or_refunded"])
    return out


def _tier(units, strong_units, category, cap):
    weak, moderate, strong = THRESHOLDS[category]
    tier = 0
    if units >= weak:
        tier = 1
    if moderate is not None and strong_units >= moderate:
        tier = 2
    if strong is not None and strong_units >= strong:
        tier = 3
    return min(tier, cap)


def pool(resolved, caps):
    """Combine resolved items of one stance into per-category unit counts and the best tier reached."""
    by_cat = {}
    for r in resolved:
        cat = r["category"]
        if cat not in REAL and cat != "C":
            continue
        b = by_cat.setdefault(cat, {"keys": set(), "strong_keys": set(), "pools": {}, "strong_pools": {}})
        b["keys"] |= r["keys"]
        b["strong_keys"] |= r["strong_keys"]
        if r["pool"] is not None:  # counted data: two items on the same survey or event share respondents, so take the max
            b["pools"][r["pool"]] = max(b["pools"].get(r["pool"], 0), r["units"])
            b["strong_pools"][r["pool"]] = max(b["strong_pools"].get(r["pool"], 0), r["strong_units"])
    cats, best = {}, 0
    for cat, b in by_cat.items():
        units = len(b["keys"]) + sum(b["pools"].values())
        strong = len(b["strong_keys"]) + sum(b["strong_pools"].values())
        cap = caps.get(cat, 0)
        tier = _tier(units, strong, cat, cap)
        cats[cat] = {"units": units, "strong_units": strong, "tier": tier, "cap": cap}
        best = max(best, tier)
    return best, cats


def grade(support_tier, contra_tier):
    """The five-step label from the two tiers. Returns (label, contested)."""
    if contra_tier >= 2 and contra_tier >= support_tier:
        return CONTRADICTED, True
    if contra_tier >= 1 and contra_tier >= support_tier:
        return LEVELS[0], True          # weak evidence both ways, or only weak evidence against: still unknown
    if contra_tier >= 1:
        return LEVELS[max(1, support_tier - 1)], True
    return LEVELS[support_tier], False


def tier_of(label):
    """The grade as a number: 0 unknown, 1 weak, 2 moderate, 3 strong. Contradicted counts as 0."""
    return LEVELS.index(label) if label in LEVELS else 0


def _evidence(store, where="", args=()):
    rows = store.rows("SELECT e.*, c.dimension, c.hypothesis_id, c.description AS claim FROM evidence e"
                      " JOIN claims c ON c.id = e.claim_id WHERE 1 = 1 " + where + " ORDER BY e.id", args)
    for e in rows:
        e["resolved"] = resolve(store, e)
    return rows


def _assess(items, caps):
    live = [e for e in items if not e["retracted_at"]]
    s_tier, s_cats = pool([e["resolved"] for e in live if e["stance"] == "supports"], caps)
    c_tier, c_cats = pool([e["resolved"] for e in live if e["stance"] == "contradicts"], caps)
    label, contested = grade(s_tier, c_tier)
    return {"level": label, "contested": contested, "tier": tier_of(label), "support_tier": s_tier, "contra_tier": c_tier,
            "support": s_cats, "contra": c_cats,
            "synthetic_items": sum(1 for e in live if e["category"] == "B"),
            "assumption_items": sum(1 for e in live if e["category"] == "A"),
            "real_items": sum(1 for e in live if e["category"] in REAL),
            "retracted_items": len(items) - len(live)}


def _missing(dim, a):
    """What it would take to move one step up, from the thresholds."""
    if a["level"] == CONTRADICTED:
        return ["The evidence against outweighs the evidence for. Change the idea, the segment or the offer, then re-test."]
    target = a["support_tier"] + 1
    out = []
    if a["contested"]:
        out.append("Real evidence against is on record, so the grade is held down until it is outweighed or explained.")
    if target > 3:
        return out
    caps, paths = CAPS[dim], []
    for cat in ("G", "F", "D", "E", "C"):
        if caps.get(cat, 0) < target:
            continue
        need = THRESHOLDS[cat][target - 1]
        if need is None:
            continue
        have = a["support"].get(cat, {}).get("strong_units" if target > 1 else "units", 0)
        if have < need:
            paths.append(((need - have) / float(need), "%d more %s (%d of %d) would reach %s" % (
                need - have, UNIT_NAMES[cat], have, need, LEVELS[target].lower())))
    return out + [text for _, text in sorted(paths, key=lambda p: p[0])]   # the closest path first


def dimensions(store, numbers=None):
    """Grade the seven questions. `numbers` is the optional unit-economics analysis (a projection)."""
    all_items = _evidence(store)
    segments = store.rows("SELECT * FROM segments")
    out = []
    for dim in DIMENSIONS:
        items = [e for e in all_items if e["dimension"] == dim]
        a = _assess(items, CAPS[dim])
        a.update({"dimension": dim, "question": QUESTIONS[dim], "items": items, "limitations": [], "missing": _missing(dim, a)})
        if a["synthetic_items"] or a["assumption_items"]:
            a["limitations"].append("%d synthetic and %d assumption item(s) are attached and carry no weight." % (
                a["synthetic_items"], a["assumption_items"]))
        if dim in WHY_NOT:
            a["limitations"].append(WHY_NOT[dim])
        if a["contested"]:
            a["limitations"].append("Real evidence points both ways. See the contradictory findings.")
        for cat, c in a["support"].items():
            if c["units"] and c["tier"] <= 1 and c["cap"] > 1 and c["strong_units"] < c["units"]:
                a["limitations"].append("%d of the %s units are opinions or stated preferences, which cannot go above weak." % (
                    c["units"] - c["strong_units"], cat))
        if dim == "segment":
            defined = [s for s in segments if s["criteria"].strip()]
            if not defined:
                a["level"], a["tier"] = LEVELS[0], 0
                a["limitations"].append("No segment has written screening criteria, so nobody can be checked against it.")
                a["missing"] = ["Define the target segment with criteria you could screen a real person against."]
        if dim == "economics":
            if numbers is None:
                a["limitations"].append("No unit-economics file (founder/numbers.json). Run founder-cfo.")
            else:
                a["projection"] = {"contribution": numbers["contribution"], "margin_at_plan": numbers["margin_at_plan"],
                                   "year1_profit": numbers["year1_profit"], "unit": numbers["unit"], "price": numbers["price"]}
                a["limitations"].append("The unit economics are a projection from the founder's inputs (an assumption)"
                                        " until acquisition cost, delivery cost and price are measured.")
        out.append(a)
    return out


AREA_DIMENSIONS = {"market": "problem", "problem": "problem", "product": "solution", "commercial": "payment",
                   "distribution": "demand"}


def hypotheses(store):
    """Every live hypothesis with its computed status and priority, most important unanswered first."""
    items = _evidence(store, "AND c.hypothesis_id IS NOT NULL")
    out = []
    for h in store.rows("SELECT * FROM hypotheses WHERE retired_at IS NULL ORDER BY id"):
        mine = [e for e in items if e["hypothesis_id"] == h["id"]]
        a = _assess(mine, GENERIC_CAPS)
        answered = a["level"] in (LEVELS[2], LEVELS[3], CONTRADICTED)
        effort = (h["test_cost"] + h["test_time"]) / 2.0
        h.update({"status": a["level"], "contested": a["contested"], "support": a["support"], "contra": a["contra"],
                  "explored_synthetically": a["synthetic_items"] > 0, "real_items": a["real_items"],
                  "answered": answered, "priority": round(h["impact"] * h["uncertainty"] / effort, 2),
                  "evidence_ids": [e["id"] for e in mine if not e["retracted_at"]]})
        out.append(h)
    out.sort(key=lambda h: (h["answered"], -h["priority"], h["id"]))
    return out


# What to run next, cheapest credible step first. cost and days are rough classes, not quotes.
PLAYBOOK = {
    "desk_research": {
        "name": "Desk research with sources", "category": "C", "cost": "free", "days": "1 to 2",
        "population": "public sources: statistics offices, industry reports, competitor price pages, review sites",
        "method": "Find at least three independent sources and record each with its link (research add).",
        "metric": "independent sources that agree on the size or direction",
        "stop": "3 independent sources, or half a day without finding one",
        "outcomes": {"supports": "Sources agree: the claim is plausible. It is still only weak evidence about YOUR customers.",
                     "contradicts": "Sources say the market or need is smaller than assumed: revise the hypothesis before anything else.",
                     "unclear": "No good sources exist: treat the claim as unknown and go ask people."}},
    "problem_interviews": {
        "name": "Problem-discovery interviews", "category": "D", "cost": "free to low (time, small thank-you gifts)", "days": "7 to 14",
        "population": "people who match the segment's screening criteria and are not friends or family",
        "method": "20 to 30 minute conversations about the last time the situation came up. No pitch, no solution.",
        "metric": "participants who describe a specific past instance AND something they did or paid about it",
        "stop": "10 interviews; stop at 5 if none can recall a specific instance",
        "outcomes": {"supports": "Most describe a recent instance and a workaround or spend: the problem is real for these people.",
                     "contradicts": "Most cannot recall an instance or shrug it off: the problem is not felt. Change segment or problem.",
                     "unclear": "Mixed: look for the subgroup that feels it and narrow the segment."}},
    "behaviour_survey": {
        "name": "Screened survey about past behaviour", "category": "E", "cost": "low to medium (panel or outreach)", "days": "5 to 10",
        "population": "screened respondents in the segment, reached through a channel you record",
        "method": "Short survey: screening first, then frequency and spend in the last 3 months. Stated-preference questions last.",
        "metric": "share of valid screened respondents reporting the behaviour in the last 3 months",
        "stop": "30 valid answers for a first read, 100 before quoting a percentage",
        "outcomes": {"supports": "The behaviour is common among those reached. It says how often, not whether they would buy.",
                     "contradicts": "The behaviour is rare: the interviews found an unusual group.",
                     "unclear": "Too few valid answers: fix recruitment before reading anything."}},
    "solution_interviews": {
        "name": "Solution-testing sessions", "category": "D", "cost": "free to low", "days": "7 to 14",
        "population": "people already confirmed to have the problem",
        "method": "Show a mock-up or walk through the service by hand. Watch what they do. Ask what they would stop using.",
        "metric": "participants who complete the core task and name what it would replace",
        "stop": "5 to 8 sessions",
        "outcomes": {"supports": "People can use it and name what it replaces: move to a concierge or pilot with a price.",
                     "contradicts": "People cannot use it or would keep their current way: the solution does not fit.",
                     "unclear": "They like it but name nothing it replaces: liking is not adoption."}},
    "landing_page": {
        "name": "Landing page test with a real call to action", "category": "F", "cost": "low to medium (page plus traffic)", "days": "7 to 21",
        "population": "qualified visitors from a channel where the segment actually is",
        "method": "One page, plain claims, the price shown, one action (book a demo, pre-order). Record traffic source and qualification.",
        "metric": "qualified visitors who take the action",
        "stop": "set min qualified visitors before launch (plan-sample), and a maximum number of days",
        "outcomes": {"supports": "Qualified people act at or above your success line: demand signal. Next, ask for money.",
                     "contradicts": "Qualified people see the offer and do not act: weak offer, wrong message or weak need.",
                     "unclear": "Mostly unqualified traffic: the test said nothing. Fix the channel."}},
    "price_test": {
        "name": "Real offer at two prices", "category": "F", "cost": "low", "days": "7 to 21",
        "population": "qualified prospects, split at random between prices",
        "method": "Same offer, two prices, real quotes or checkout. Honour whichever price each person saw.",
        "metric": "qualified prospects who accept at each price",
        "stop": "planned sample per price, set before launch",
        "outcomes": {"supports": "Acceptance holds at the higher price: price there.",
                     "contradicts": "Acceptance collapses at both prices: the problem is value, not price.",
                     "unclear": "No detectable difference at this sample: do not claim either price is better."}},
    "preorder": {
        "name": "Pre-order or refundable deposit", "category": "G", "cost": "low", "days": "7 to 21",
        "population": "qualified prospects who have seen the full offer and terms",
        "method": "Take a real, clearly refundable deposit with a delivery date. State the terms in writing. Charge only with consent.",
        "metric": "qualified prospects who pay a deposit, net of cancellations",
        "stop": "a set number of offers made, or a set date",
        "outcomes": {"supports": "People put money down and do not cancel: the strongest pre-build signal there is.",
                     "contradicts": "Interest but no deposits: stated interest was politeness.",
                     "unclear": "Deposits then cancellations: find out what changed between yes and no."}},
    "concierge": {
        "name": "Concierge MVP: deliver it by hand", "category": "G", "cost": "low to medium (your time)", "days": "14 to 30",
        "population": "3 to 10 paying customers from the segment",
        "method": "Sell the outcome, deliver it manually, charge the planned price. Log hours and costs per customer.",
        "metric": "customers who pay and come back, and the measured cost to serve one",
        "stop": "10 customers or 30 days",
        "outcomes": {"supports": "They pay, return, and the cost to serve leaves a margin: build the parts that hurt most to do by hand.",
                     "contradicts": "They will not pay, or serving them costs more than the price: fix the economics before building.",
                     "unclear": "They pay once and do not return: find out why before automating anything."}},
    "pilot": {
        "name": "Paid B2B pilot", "category": "G", "cost": "medium (sales time)", "days": "30 to 90",
        "population": "qualified accounts where you have met the budget owner",
        "method": "A scoped, paid pilot with written success criteria and a conversion price agreed up front.",
        "metric": "pilots signed, completed and converted to a paid contract; days from first meeting to signature",
        "stop": "3 to 5 pilots offered",
        "outcomes": {"supports": "Pilots are paid for and convert: commercial demand and a measured sales cycle.",
                     "contradicts": "Only free pilots are accepted: interest without budget.",
                     "unclear": "Pilots complete but stall at procurement: you have not reached the buyer."}},
    "channel_test": {
        "name": "Small channel test with measured cost", "category": "F", "cost": "low to medium (a fixed budget)", "days": "7 to 14",
        "population": "the segment, reached through one channel at a time",
        "method": "A fixed small budget per channel, the same page and offer, cost recorded per event.",
        "metric": "cost per qualified lead, per channel",
        "stop": "the fixed budget is spent",
        "outcomes": {"supports": "At least one channel delivers qualified leads below what a customer is worth.",
                     "contradicts": "Every channel costs more per customer than the margin allows.",
                     "unclear": "Too few qualified leads to compare channels: widen the budget or pick one."}},
}
LADDERS = {
    "market": ["desk_research", "behaviour_survey"],
    "problem": ["problem_interviews", "behaviour_survey"],
    "product": ["solution_interviews", "concierge"],
    "commercial": ["problem_interviews", "price_test", "preorder", "pilot"],
    "distribution": ["landing_page", "channel_test"],
}


def recommend(store, dims=None, hyps=None):
    """The most important unanswered question and the cheapest credible experiment for it."""
    dims = dims or dimensions(store)
    hyps = hyps or hypotheses(store)
    level = {d["dimension"]: d for d in dims}
    open_h = [h for h in hyps if not h["answered"]]
    contradicted = [h for h in hyps if h["status"] == CONTRADICTED]
    if not hyps:
        return {"question": None, "note": "No hypotheses yet. List what must be true for this business to work first."}
    if not open_h:
        return {"question": None, "contradicted": [h["id"] for h in contradicted],
                "note": "Every hypothesis has at least moderate evidence for or against. Review the contradicted ones."}
    h = open_h[0]
    problem_ok = level["problem"]["tier"] >= 2
    ladder = LADDERS[h["area"]]
    have = set(h["support"]) | set(h["contra"])
    step = next((s for s in ladder if PLAYBOOK[s]["category"] not in have), ladder[-1])
    prerequisite = None
    if h["area"] in ("product", "commercial", "distribution") and not problem_ok:
        prerequisite = ("Problem evidence is '%s'. Testing the solution, price or channel for a problem nobody has proven"
                        " is wasted money. Run problem interviews first." % level["problem"]["level"])
        step = "problem_interviews"
    exp = dict(PLAYBOOK[step], id=step)
    running = store.rows("SELECT id, title FROM experiments WHERE hypothesis_id = ? AND status IN ('designed', 'running')", (h["id"],))
    return {"question": h["statement"], "hypothesis_id": h["id"], "area": h["area"], "priority": h["priority"],
            "why": "Impact if false %d of 5, uncertainty %d of 5, cost to test %d of 5, time to test %d of 5. Current status: %s." % (
                h["impact"], h["uncertainty"], h["test_cost"], h["test_time"], h["status"].lower()),
            "if_false": h["if_false"], "experiment": exp, "prerequisite": prerequisite,
            "already_planned": running,
            "do_not_build": None if (problem_ok and level["demand"]["tier"] >= 2) else
            "Do not pay for product development yet: the problem and qualified demand are not both at least moderately supported.",
            "contradicted": [x["id"] for x in contradicted]}


def verdict(dims):
    """Go / Conditional Go / No-Go, or an honest refusal to recommend. Computed from the seven grades."""
    level = {d["dimension"]: d for d in dims}
    tier = lambda k: level[k]["tier"]
    against = [k for k in DIMENSIONS if level[k]["level"] == CONTRADICTED]
    gaps = [k for k in DIMENSIONS if level[k]["level"] != CONTRADICTED and level[k]["tier"] < 2]
    if any(k in against for k in ("problem", "demand", "payment", "economics")):
        return {"decision": "No-Go", "because": against, "conditions": [],
                "text": "Real evidence contradicts %s. Do not invest further in this version of the idea." % " and ".join(against)}
    if not gaps and not against:
        return {"decision": "Go", "because": list(DIMENSIONS), "conditions": [],
                "text": "All seven questions have at least moderate real evidence and none is contradicted. The evidence"
                        " justifies the next stage of investment. It does not guarantee the business."}
    if tier("problem") >= 2 and (tier("demand") >= 1 or tier("behavior") >= 1 or tier("payment") >= 1):
        return {"decision": "Conditional Go", "because": [k for k in DIMENSIONS if k not in gaps and k not in against],
                "conditions": gaps + against,
                "text": "The problem is supported and there is some real demand signal. Continue only to close these gaps: %s."
                        % ", ".join(gaps + against)}
    return {"decision": "No recommendation yet", "because": [], "conditions": gaps + against,
            "text": "There is not enough real evidence to recommend for or against. Saying Go or No-Go now would be a guess."
                    " Still unknown or weak: %s." % ", ".join(gaps + against)}


# ── calibration ─────────────────────────────────────────────────────────────────
MIN_COMPARABLE = 5


def add_prediction(store, p):
    for k in ("source", "prediction_type", "measured_what", "predicted"):
        if p.get(k) in (None, ""):
            raise StoreError("a prediction needs '%s'" % k)
    model = p.get("model", "")
    if p["source"] == "synthetic":
        run = store.get("syn_runs", p.get("run_id"), "synthetic run")
        model = model or run["model"]
    return store.insert("predictions", {
        "source": p["source"], "run_id": p.get("run_id"), "prediction_type": p["prediction_type"],
        "measured_what": p["measured_what"], "predicted": float(p["predicted"]), "model": model,
        "scenario": p.get("scenario", ""), "methodology": p.get("methodology", ""),
        "segment_id": p.get("segment_id"), "price_point": p.get("price_point"), "made_at": now()})


def predict_from_run(store, rid, arm, segment_id=None):
    """Record a synthetic run's stance share as a prediction, so reality can be set against it later."""
    t = synth.tally(store, rid)
    block = (t.get("concept") or {}).get(arm)
    if not block or block["calibration_only"]["value"] is None:
        raise StoreError("run %s has no concept-stage answers for arm %r" % (rid, arm))
    run = store.get("syn_runs", rid)
    arms = {a["id"]: a for a in json.loads(run["arms_json"])}
    price = arms[arm].get("price")
    return add_prediction(store, {
        "source": "synthetic", "run_id": rid, "prediction_type": "interest_share",
        "measured_what": block["calibration_only"]["measure"], "predicted": block["calibration_only"]["value"],
        "scenario": arms[arm]["scenario"], "methodology": "%s, seed %s, %d profiles, quota-dealt dispositions" % (
            run["prompt_version"], run["seed"], run["n_personas"]),
        "segment_id": segment_id, "price_point": price if isinstance(price, (int, float)) else None})


def add_outcome(store, o):
    for k in ("prediction_id", "experiment_id", "event", "denominator", "measured_what", "comparable_note"):
        if o.get(k) in (None, ""):
            raise StoreError("an outcome needs '%s'" % k)
    if not isinstance(o.get("comparable"), bool):
        raise StoreError("say whether the two numbers measure the same thing: comparable true or false, with comparable_note")
    p = store.get("predictions", o["prediction_id"], "prediction")
    x = store.get("experiments", o["experiment_id"], "experiment")
    if x["launched_at"] is None:
        raise StoreError("%s has not launched" % x["id"])
    if x["completed_at"] and x["completed_at"] < p["made_at"]:
        raise StoreError("%s was recorded after %s had finished. A number written down after the result is known is not a"
                         " prediction." % (p["id"], x["id"]))
    return store.insert("outcomes", {"prediction_id": p["id"], "experiment_id": x["id"], "measured_what": o["measured_what"],
                                     "event": o["event"], "denominator": o["denominator"],
                                     "comparable": int(o["comparable"]), "comparable_note": o["comparable_note"],
                                     "recorded_at": now()})


def calibration(store):
    """Set each prediction beside what actually happened. Never blends the two into one number."""
    segs = {s["id"]: s["name"] for s in store.rows("SELECT id, name FROM segments")}
    pairs = []
    for o in store.rows("SELECT * FROM outcomes ORDER BY id"):
        p = store.get("predictions", o["prediction_id"])
        x = store.get("experiments", o["experiment_id"])
        c = experiments.counts(store, x["id"], o["event"], o["denominator"])
        actual = stats.rate(c["k"], c["n"]) if c["k"] <= c["n"] else None
        lo, hi = stats.wilson(c["k"], c["n"]) if actual is not None else (None, None)
        design = json.loads(x["design_json"])
        reasons = ["They measure different things: the prediction is '%s'; the result is '%s'. A stated or simulated"
                   " stance is not an action." % (p["measured_what"], o["measured_what"])]
        if p["segment_id"] != x["segment_id"]:
            reasons.append("Different audience: predicted for %s, measured on %s." % (
                segs.get(p["segment_id"], "an unspecified segment"), segs.get(x["segment_id"], "an unspecified segment")))
        prices = set((design.get("price_points") or {}).values())
        if p["price_point"] is not None and prices and p["price_point"] not in prices:
            reasons.append("Different price: predicted at %s, tested at %s." % (p["price_point"], ", ".join(str(v) for v in sorted(prices))))
        if c["unknown_n"] or c["unqualified_n"]:
            reasons.append("%d visitors were unqualified or of unknown quality and are outside the measured rate." % (
                c["unknown_n"] + c["unqualified_n"]))
        if p["source"] == "synthetic":
            reasons.append("Simulated profiles lean agreeable, and their mix was set by quota, not by the market.")
        reasons += ["The problem may matter less than assumed.", "The offer or message on the page may be weak or unclear.",
                    "The price may be too high for the value shown."]
        pairs.append({"prediction_id": p["id"], "experiment_id": x["id"], "source": p["source"], "model": p["model"],
                      "prediction_type": p["prediction_type"], "segment": segs.get(p["segment_id"]),
                      "scenario": p["scenario"], "methodology": p["methodology"], "predicted": p["predicted"],
                      "predicted_measure": p["measured_what"], "actual": actual, "actual_k": c["k"], "actual_n": c["n"],
                      "actual_low": lo, "actual_high": hi, "actual_measure": o["measured_what"],
                      "difference": (p["predicted"] - actual) if actual is not None else None,
                      "comparable": bool(o["comparable"]), "comparable_note": o["comparable_note"],
                      "made_at": p["made_at"], "possible_reasons": reasons})
    groups = {}
    for pr in pairs:
        if pr["comparable"] and pr["actual"] is not None:
            groups.setdefault((pr["source"], pr["model"], pr["prediction_type"]), []).append(pr)
    summary = []
    for (source, model, ptype), items in sorted(groups.items()):
        row = {"source": source, "model": model, "prediction_type": ptype, "comparable_pairs": len(items),
               "needed": MIN_COMPARABLE}
        if len(items) >= MIN_COMPARABLE:
            over = sum(1 for i in items if i["difference"] > 0)
            under = sum(1 for i in items if i["difference"] < 0)
            row.update({"mean_signed_error": sum(i["difference"] for i in items) / len(items), "over": over, "under": under,
                        "sign_test_p": stats.sign_test(over, under),
                        "says": "Across %d comparable cases this source %s by %.1f points on average (%d over, %d under)." % (
                            len(items), "overestimated" if sum(i["difference"] for i in items) > 0 else "underestimated",
                            abs(sum(i["difference"] for i in items) / len(items)) * 100, over, under)})
        else:
            row["says"] = "Only %d comparable prediction/result pair(s); %d are needed before any calibration figure is computed." % (
                len(items), MIN_COMPARABLE)
        summary.append(row)
    open_predictions = store.rows("SELECT * FROM predictions WHERE id NOT IN (SELECT prediction_id FROM outcomes) ORDER BY id")
    return {"pairs": pairs, "summary": summary, "open_predictions": open_predictions,
            "calibrated": any(r["comparable_pairs"] >= MIN_COMPARABLE for r in summary),
            "statement": "Not calibrated: there are fewer than %d comparable real results to check predictions against."
                         " The number of synthetic answers does not change this." % MIN_COMPARABLE
            if not any(r["comparable_pairs"] >= MIN_COMPARABLE for r in summary) else
            "Calibration figures exist for the groups listed. They describe past error for that model, segment and"
            " prediction type only."}


# ── pricing ─────────────────────────────────────────────────────────────────────
def pricing(store, van_westendorp=None):
    """Six kinds of price evidence, side by side and never merged. `van_westendorp` is the founder-pricing module."""
    out = {"layers": []}

    def vw(rows):
        if van_westendorp is None or len(rows) < 5:
            return None
        res = van_westendorp.analyse(rows)
        return {"n": res["n"], "points": res["points"]}

    for run in store.rows("SELECT * FROM syn_runs ORDER BY id"):
        rows = synth.price_rows(store, run["id"])
        if rows:
            out["layers"].append({"layer": 1, "name": "Synthetic price exploration", "category": "B", "ref": run["id"],
                                  "n": len(rows), "van_westendorp": vw(rows),
                                  "reading": "Simulated. Use only to choose which prices to put in front of real people."})
    spend = research.analyse_interviews(store)["spend"]
    if spend:
        out["layers"].append({"layer": 2, "name": "What interviewed customers already spend", "category": "D",
                              "n": len({s["participant"] for s in spend}), "items": spend,
                              "reading": "Reported past spending on the problem or on alternatives. The best pre-launch price anchor."})
    for sv in store.rows("SELECT id, title FROM surveys ORDER BY id"):
        p = research.survey_prices(store, sv["id"])
        if p["van_westendorp"] or p["gabor_granger"]:
            layer = {"layer": 3, "name": "Survey price research", "category": "E", "ref": sv["id"],
                     "n": max(len(p["van_westendorp"]), len(p["gabor_granger"])), "van_westendorp": vw(p["van_westendorp"]),
                     "reading": "Stated willingness to pay from real respondents. Exploratory: people overstate what they will pay."}
            if len(p["gabor_granger"]) >= 5:
                layer["gabor_granger"] = stats.gabor_granger(p["gabor_granger"])
            out["layers"].append(layer)
    comp = store.rows("SELECT id, title, url, price, currency, price_includes, accessed_on FROM research_sources"
                      " WHERE kind = 'competitor_price' AND price IS NOT NULL ORDER BY price")
    if comp:
        out["layers"].append({"layer": 4, "name": "Competitor and substitute prices", "category": "C", "n": len(comp),
                              "items": comp, "reading": "What the alternatives charge, with links. Check what each price includes."})
    for x in store.rows("SELECT id, title, type FROM experiments WHERE launched_at IS NOT NULL ORDER BY id"):
        r = experiments.read(store, x["id"], record_look=False)
        priced = [a for a in r["arms"] if a["price_point"] is not None and a["n"]]
        if priced:
            out["layers"].append({"layer": 5, "name": "Real offers", "category": "F", "ref": x["id"], "title": x["title"],
                                  "arms": [{"price": a["price_point"], "k": a["k"], "n": a["n"], "rate": a["rate"],
                                            "low": a["low"], "high": a["high"]} for a in priced],
                                  "comparisons": r.get("comparisons"), "outcome": r["outcome"],
                                  "reading": "Qualified prospects accepting a real offer at each price."})
    m = experiments.money(store)
    if m["transactions"]:
        out["layers"].append({"layer": 6, "name": "Actual transactions", "category": "G", "n": m["n_payers"],
                              "payers_by_price": m["payers_by_price"], "net_revenue": m["net_revenue"],
                              "currencies": m["currencies"], "repeat_payers": len(m["repeat_payers"]),
                              "reading": "Money that changed hands, net of refunds and cancellations. The only layer that proves a price."})
    roles = {r["role"]: r["n"] for r in store.rows(
        "SELECT role, COUNT(*) AS n FROM participants WHERE status = 'interviewed' AND redacted_at IS NULL GROUP BY role")}
    out["roles_interviewed"] = roles
    out["role_gap"] = [r for r in ("buyer", "budget_owner") if not roles.get(r)]
    out["highest_layer"] = max([l["layer"] for l in out["layers"]] or [0])
    return out


def snapshot(store, numbers=None, van_westendorp=None):
    """Everything the report and the dashboard show, computed in one pass."""
    dims = dimensions(store, numbers)
    hyps = hypotheses(store)
    segs = {s["id"]: s for s in store.rows("SELECT * FROM segments ORDER BY id")}
    claims = []
    all_items = [e for d in dims for e in d["items"]]
    for c in store.rows("SELECT * FROM claims ORDER BY id"):
        mine = [e for e in all_items if e["claim_id"] == c["id"]]
        a = _assess(mine, CAPS[c["dimension"]])
        live = [e for e in mine if not e["retracted_at"] and e["stance"] == "supports"]
        best = max([e["category"] for e in live] or ["A"]) if live else None
        c.update({"confidence": a["level"], "contested": a["contested"], "strongest_category": best,
                  "segment": (segs.get(c["segment_id"]) or {}).get("name"),
                  "supporting": [_public(e) for e in mine if e["stance"] == "supports"],
                  "contradicting": [_public(e) for e in mine if e["stance"] == "contradicts"]})
        claims.append(c)
    runs = []
    for r in store.rows("SELECT * FROM syn_runs ORDER BY id"):
        n = store.one("SELECT COUNT(*) AS n FROM syn_responses WHERE run_id = ?", (r["id"],))["n"]
        runs.append(dict(r, responses=n, tally=synth.tally(store, r["id"]) if n else None))
    xs = [experiments.read(store, x["id"], record_look=False) for x in store.rows("SELECT id FROM experiments ORDER BY id")]
    surveys = [research.analyse_survey(store, s["id"]) for s in store.rows("SELECT id FROM surveys ORDER BY id")]
    ok, entries, bad = store.verify_audit()
    return {
        "project": store.meta("project_name"), "rules_version": RULES_VERSION, "generated_at": now(),
        "concepts": store.rows("SELECT * FROM concepts ORDER BY id"), "segments": list(segs.values()),
        "dimensions": [dict(d, items=[_public(e) for e in d["items"]]) for d in dims],
        "hypotheses": hyps, "claims": claims, "recommendation": recommend(store, dims, hyps), "verdict": verdict(dims),
        "synthetic_runs": runs, "interviews": research.analyse_interviews(store), "surveys": surveys,
        "recruitment": research.recruitment(store), "experiments": xs, "money": experiments.money(store),
        "research_sources": store.rows("SELECT * FROM research_sources ORDER BY id"),
        "pricing": pricing(store, van_westendorp), "calibration": calibration(store),
        "numbers": numbers, "audit": {"ok": ok, "entries": entries, "first_bad": bad},
        "counts": {
            "synthetic_responses": store.one("SELECT COUNT(*) AS n FROM syn_responses")["n"],
            "real_people_interviewed": store.one("SELECT COUNT(DISTINCT participant_id) AS n FROM interviews i JOIN participants p"
                                                 " ON p.id = i.participant_id WHERE p.redacted_at IS NULL")["n"],
            "valid_survey_responses": store.one("SELECT COUNT(*) AS n FROM survey_responses WHERE excluded_reason IS NULL")["n"],
            "qualified_actions": sum(a["k"] for x in xs for a in x["arms"]),
            "paying_customers": experiments.money(store)["n_payers"]},
    }


def _public(e):
    r = e["resolved"]
    return {"id": e["id"], "claim_id": e["claim_id"], "dimension": e["dimension"], "stance": e["stance"],
            "category": e["category"], "category_name": CATEGORIES[e["category"]], "knowledge": KNOWLEDGE[e["category"]],
            "real": e["category"] in REAL, "method": e["method"], "collected_on": e["collected_on"],
            "segment_id": e["segment_id"], "summary": e["summary"], "limitations": e["limitations"],
            "origin": e["origin"], "ref": json.loads(e["ref_json"]), "resolved": r["detail"],
            "k": r.get("k"), "n": r.get("n"),
            "units": len(r["keys"]) + r["units"], "retracted_at": e["retracted_at"], "retract_reason": e["retract_reason"]}
