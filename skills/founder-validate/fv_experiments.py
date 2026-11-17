"""Behavioural experiments and transactions for founder-validate. Standard library only.

This is where the record moves from what customers say to what they do. The
tool does not run a landing page, send traffic or take a payment. It holds the
design you committed to BEFORE launch, the counts and payments you import from
the systems that did the work, and the reading of the result against the rule
you wrote down in advance.

Rules it enforces:
  - no launch without a complete design (metric, population, stopping rule,
    decision rule, what each outcome will mean);
  - the design cannot be edited after launch, only amended on the record;
  - only QUALIFIED traffic enters a conversion rate; unqualified and
    unknown-quality traffic is shown beside it, never inside it;
  - a payment needs explicit authorisation and a receipt reference;
  - reading an A/B test before its planned sample is counted as a look and
    labelled interim; a winner needs the sample, the significance level and the
    minimum effect you set in advance.
"""

import csv
import datetime
import json
import os

import fv_stats as stats
from fv_store import MONEY_IN, MONEY_OUT, StoreError, _float, canonical, check_date, now, sha256_file, today

MULTI_ARM = ("ab_test", "price_test")
TYPE_HINTS = {
    "landing_page": "qualified visitors who take the action (demo request, signup, pre-order click)",
    "price_test": "qualified prospects who accept the offer at each price",
    "preorder": "qualified prospects who put money down",
    "concierge": "customers served by hand who pay and come back",
    "pilot": "qualified prospects who sign, complete and convert a pilot",
    "ab_test": "the difference in one metric between two versions",
}


def validate_design(xtype, d):
    """Return a list of what is missing from an experiment design. Empty list = ready to register."""
    if not isinstance(d, dict):
        return ["design: an object with the fields in references/experiments.md"]
    for key in ("primary_metric", "stopping_rule", "decision_rule", "outcomes", "price_points"):
        if key in d and not isinstance(d[key], dict):
            return ["%s: must be an object" % key]
    if "variants" in d and (not isinstance(d["variants"], list) or not all(isinstance(v, str) and v for v in d["variants"])
                            or len(set(d["variants"])) != len(d["variants"])):
        return ["variants: a list of distinct names, the control first"]
    miss = []
    for k, why in (("learn", "what you need to learn"), ("population", "who is being tested"),
                   ("method", "how the test runs"), ("qualification", "what makes a visitor or prospect count as qualified")):
        if not str(d.get(k) or "").strip():
            miss.append("%s: %s" % (k, why))
    pm = d.get("primary_metric") or {}
    if not pm.get("event") or not pm.get("denominator"):
        miss.append("primary_metric: the one event that decides the test and its denominator event")
    elif pm["event"] == pm["denominator"]:
        miss.append("primary_metric: the event and its denominator cannot be the same")
    stop = d.get("stopping_rule") or {}
    if not _posint(stop.get("min_denominator_per_variant")) or not _posint(stop.get("max_days")):
        miss.append("stopping_rule: min_denominator_per_variant and max_days, decided before launch")
    rule = d.get("decision_rule") or {}
    if xtype in MULTI_ARM:
        if len(d.get("variants") or []) < 2:
            miss.append("variants: at least two, the first is the control")
        if not _unit(rule.get("min_effect")):
            miss.append("decision_rule.min_effect: the smallest absolute difference worth acting on (for example 0.02)")
        if "alpha" in rule and not (_unit(rule["alpha"]) and rule["alpha"] < 1):
            miss.append("decision_rule.alpha: a significance level between 0 and 1 (default 0.05)")
        if d.get("price_points") and not all(_number(v) and v > 0 for v in d["price_points"].values()):
            miss.append("price_points: every price must be a positive number")
        if xtype == "price_test":
            pp = d.get("price_points") or {}
            if set(pp) != set(d.get("variants") or []) or len(set(pp.values())) < 2:
                miss.append("price_points: one distinct price per variant")
    else:
        if not _unit(rule.get("success_at")) or not _number(rule.get("fail_below")) or not 0 <= rule["fail_below"] <= rule["success_at"]:
            miss.append("decision_rule: success_at and fail_below as rates (0.05 = 5%), fail_below not above success_at")
    out = d.get("outcomes") or {}
    for k in ("success", "failure", "inconclusive"):
        if not str(out.get(k) or "").strip():
            miss.append("outcomes.%s: what you will conclude and do if the result is a %s" % (k, k))
    if not _number(d.get("cost_estimate")) or not _number(d.get("days_estimate")):
        miss.append("cost_estimate and days_estimate, as numbers")
    if xtype in ("preorder", "price_test", "pilot", "concierge") and not str(d.get("offer_terms") or "").strip():
        miss.append("offer_terms: exactly what the customer is told about price, delivery date, refunds and when they are charged")
    return miss


def _posint(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _unit(v):
    return _number(v) and 0 < v <= 1


def register(store, x):
    """Record a design. This is the pre-registration: it is dated and audited before any data exists."""
    if not isinstance(x, dict):
        raise StoreError("an experiment must be a JSON object")
    for k in ("type", "title", "design"):
        if not x.get(k):
            raise StoreError("experiment needs '%s'" % k)
    miss = validate_design(x["type"], x["design"])
    if miss:
        raise StoreError("the design is not complete. Decide these before launch:\n  - " + "\n  - ".join(miss))
    if x.get("hypothesis_id"):
        store.get("hypotheses", x["hypothesis_id"], "hypothesis")
    return store.insert("experiments", {
        "type": x["type"], "title": x["title"], "hypothesis_id": x.get("hypothesis_id"),
        "concept_id": x.get("concept_id"), "segment_id": x.get("segment_id"),
        "design_json": canonical(x["design"]), "status": "designed", "registered_at": now()})


def launch(store, xid, launched_on=None):
    x = store.get("experiments", xid, "experiment")
    if x["status"] != "designed":
        raise StoreError("%s is already %s" % (xid, x["status"]))
    day = check_date(launched_on or today(), "launched_on")
    if day < x["registered_at"][:10]:
        raise StoreError("%s was registered on %s. A launch date before that would mean the data came before the design:"
                         " that is not a pre-registered test." % (xid, x["registered_at"][:10]))
    store.update("experiments", xid, {"status": "running", "launched_at": day}, action="launch")


def amend(store, xid, change, reason):
    x = store.get("experiments", xid, "experiment")
    if not (change or "").strip() or not (reason or "").strip():
        raise StoreError("an amendment needs what changed and why")
    store.insert("experiment_amendments", {"experiment_id": x["id"], "at": now(), "change": change, "reason": reason})


def _running(store, xid, what):
    x = store.get("experiments", xid, "experiment")
    if x["launched_at"] is None:
        raise StoreError("%s has not launched. Launch it first; data from before launch is not part of the test." % xid)
    if x["status"] == "abandoned":
        raise StoreError("%s was abandoned: no new %s" % (xid, what))
    if x["status"] == "completed" and what == "events":
        raise StoreError("%s is closed. Its result stands as read; run a new experiment for new data." % xid)
    return x


def record_events(store, xid, events, batch=None):
    """Record observed counts. Each needs where the number came from; nothing is estimated."""
    x = _running(store, xid, "events")
    design = json.loads(x["design_json"])
    variants = design.get("variants")
    batch = batch or "manual:%s" % now()
    ids = []
    for e in events:
        if not isinstance(e, dict):
            raise StoreError("each event must be a JSON object")
        for k in ("event", "count", "occurred_on", "origin_record"):
            if e.get(k) in (None, ""):
                raise StoreError("an event needs '%s' (origin_record = the export, dashboard or log the count came from)" % k)
        if "qualified" not in e:
            raise StoreError("an event needs 'qualified': true, false, or null when you cannot tell. Unknown is not counted"
                             " as qualified.")
        if e["qualified"] not in (True, False, None):
            raise StoreError("'qualified' must be true, false or null")
        if not isinstance(e["count"], int) or isinstance(e["count"], bool) or e["count"] < 0:
            raise StoreError("count must be a whole number, zero or more")
        day = check_date(e["occurred_on"], "occurred_on")
        if day < x["launched_at"][:10]:
            raise StoreError("%s is before the launch date %s: not part of this experiment" % (day, x["launched_at"][:10]))
        variant = e.get("variant") or (variants[0] if variants and len(variants) == 1 else "all")
        if variants and variant not in variants:
            raise StoreError("variant %r is not in the design (%s)" % (variant, ", ".join(variants)))
        ids.append(store.insert("behavior_events", {
            "experiment_id": xid, "variant": variant, "event": e["event"], "count": e["count"],
            "qualified": None if e["qualified"] is None else int(e["qualified"]), "occurred_on": day,
            "traffic_source": e.get("traffic_source", ""), "audience": e.get("audience", ""),
            "price_point": _float(e.get("price_point"), "price_point"), "cost": _float(e.get("cost"), "cost") or 0.0,
            "origin_record": e["origin_record"], "import_batch": batch}))
    return ids


def import_events_csv(store, xid, path):
    """CSV columns: occurred_on, event, count, qualified (yes/no/blank), variant, traffic_source, audience, cost, price_point."""
    if not os.path.isfile(path):
        raise StoreError("no such file: %s" % path)
    batch = "%s:%s" % (os.path.basename(path), sha256_file(path)[:12])
    if store.one("SELECT 1 AS x FROM behavior_events WHERE experiment_id = ? AND import_batch = ?", (xid, batch)):
        raise StoreError("this exact file was already imported into %s" % xid)
    events = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, r in enumerate(csv.DictReader(fh), 2):
            q = (r.get("qualified") or "").strip().lower()
            if q not in ("yes", "no", "true", "false", "1", "0", ""):
                raise StoreError("line %d: qualified must be yes, no or blank" % i)
            try:
                events.append({
                    "occurred_on": r.get("occurred_on"), "event": (r.get("event") or "").strip(),
                    "count": int(r.get("count") or ""), "qualified": None if q == "" else q in ("yes", "true", "1"),
                    "variant": (r.get("variant") or "").strip() or None, "traffic_source": (r.get("traffic_source") or "").strip(),
                    "audience": (r.get("audience") or "").strip(), "cost": float(r.get("cost") or 0),
                    "price_point": float(r["price_point"]) if (r.get("price_point") or "").strip() else None,
                    "origin_record": "imported file %s" % os.path.basename(path)})
            except ValueError:
                raise StoreError("line %d: count, cost and price_point must be numbers" % i)
    return record_events(store, xid, events, batch)


def void_event(store, event_id, reason):
    if not (reason or "").strip():
        raise StoreError("voiding needs a reason; the row stays in the record")
    if store.one("SELECT id FROM behavior_events WHERE id = ?", (event_id,)) is None:
        raise StoreError("no behaviour event %r" % event_id)
    store.update("behavior_events", event_id, {"voided_at": now(), "void_reason": reason}, action="void")


def add_transaction(store, t):
    if not isinstance(t, dict):
        raise StoreError("a transaction must be a JSON object")
    for k in ("payer_ref", "kind", "amount", "currency", "occurred_on", "reference"):
        if t.get(k) in (None, ""):
            raise StoreError("a transaction needs '%s' (reference = the receipt, invoice or contract id)" % k)
    if t.get("authorized") is not True:
        raise StoreError("a transaction is recorded only with authorized: true, meaning the customer explicitly agreed to"
                         " this charge or signed this contract. Never charge anyone without it.")
    if t.get("experiment_id"):
        _running(store, t["experiment_id"], "transactions")
    if t.get("participant_id"):
        store.get("participants", t["participant_id"], "participant")
    amount = _float(t["amount"], "amount")
    return store.insert("transactions", {
        "experiment_id": t.get("experiment_id"), "participant_id": t.get("participant_id"),
        "payer_ref": str(t["payer_ref"]), "kind": t["kind"], "amount": amount, "currency": t["currency"],
        "price_point": _float(t.get("price_point"), "price_point"), "variant": t.get("variant") or "all",
        "occurred_on": check_date(t["occurred_on"], "occurred_on"), "reference": str(t["reference"]),
        "authorized": 1, "segment_id": t.get("segment_id")})


def void_transaction(store, tid, reason):
    if not (reason or "").strip():
        raise StoreError("voiding needs a reason; the row stays in the record")
    store.get("transactions", tid, "transaction")
    store.update("transactions", tid, {"voided_at": now(), "void_reason": reason}, action="void")


def payers(rows):
    """From transaction rows: {payer_ref: net amount}. Refunds and cancellations subtract. Net <= 0 is not a payer."""
    net = {}
    for t in rows:
        if t.get("voided_at"):
            continue
        sign = 1.0 if t["kind"] in MONEY_IN else (-1.0 if t["kind"] in MONEY_OUT else 0.0)
        net[t["payer_ref"]] = net.get(t["payer_ref"], 0.0) + sign * t["amount"]
    return net


def money(store, experiment_id=None, ids=None):
    """Transaction summary for an experiment, a list of ids, or everything."""
    if ids:
        rows = store.rows("SELECT * FROM transactions WHERE id IN (%s)" % ", ".join("?" * len(ids)), list(ids))
    elif experiment_id:
        rows = store.rows("SELECT * FROM transactions WHERE experiment_id = ?", (experiment_id,))
    else:
        rows = store.rows("SELECT * FROM transactions")
    live = [t for t in rows if not t["voided_at"]]
    # Net each payer over EVERYTHING they did, not only the rows selected here: a refund filed against another
    # experiment, or simply left out of the selection, still means the customer did not pay.
    everything = payers(store.rows("SELECT * FROM transactions WHERE voided_at IS NULL"))
    net = {p: everything.get(p, 0.0) for p in {t["payer_ref"] for t in live}}
    paying = sorted(p for p, v in net.items() if v > 0)
    repeat = sorted({t["payer_ref"] for t in live if t["kind"] == "repeat_payment"} & set(paying))
    currencies = sorted({t["currency"] for t in live})
    by_kind = {}
    for t in live:
        k = by_kind.setdefault(t["kind"], {"count": 0, "amount": 0.0})
        k["count"] += 1
        k["amount"] += t["amount"]
    by_price = {}
    for t in live:
        if t["price_point"] is None or t["kind"] not in MONEY_IN:
            continue
        by_price.setdefault(t["price_point"], set()).add(t["payer_ref"])
    return {"payers": paying, "n_payers": len(paying), "repeat_payers": repeat,
            "cancelled_or_refunded": sorted(p for p, v in net.items() if v <= 0),
            "net_revenue": sum(v for v in net.values() if v > 0) if len(currencies) <= 1 else None,
            "currencies": currencies, "by_kind": by_kind,
            "payers_by_price": {p: len(v & set(paying)) for p, v in sorted(by_price.items())},
            "transactions": [t["id"] for t in live]}


def _sum(events, event, variant, qualified):
    """Total count of one event in one variant. qualified: 1, 0 or None (unknown)."""
    return sum(e["count"] for e in events if e["event"] == event and (variant is None or e["variant"] == variant)
               and e["qualified"] == qualified)


def counts(store, xid, event, denominator, variant=None):
    """Qualified (k, n) for an event over its denominator, plus what was left out."""
    events = store.rows("SELECT * FROM behavior_events WHERE experiment_id = ? AND voided_at IS NULL", (xid,))
    return {"k": _sum(events, event, variant, 1), "n": _sum(events, denominator, variant, 1),
            "unqualified_n": _sum(events, denominator, variant, 0), "unknown_n": _sum(events, denominator, variant, None),
            "unqualified_k": _sum(events, event, variant, 0), "unknown_k": _sum(events, event, variant, None)}


def read(store, xid, record_look=True):
    """Read an experiment against its pre-registered design. Returns a dict; changes nothing but the look counter."""
    x = store.get("experiments", xid, "experiment")
    d = json.loads(x["design_json"])
    pm, stop, rule = d["primary_metric"], d["stopping_rule"], d.get("decision_rule") or {}
    events = store.rows("SELECT * FROM behavior_events WHERE experiment_id = ? AND voided_at IS NULL", (xid,))
    variants = d.get("variants") or ["all"]
    need = stop["min_denominator_per_variant"]
    arms, problems = [], []
    for v in variants:
        c = counts(store, xid, pm["event"], pm["denominator"], v if d.get("variants") else None)
        if c["k"] > c["n"]:
            problems.append("variant %s has %d qualified '%s' but only %d qualified '%s': check the import" % (
                v, c["k"], pm["event"], c["n"], pm["denominator"]))
            lo = hi = r = None
        else:
            r = stats.rate(c["k"], c["n"])
            lo, hi = stats.wilson(c["k"], c["n"])
        cost = sum(e["cost"] for e in events if (not d.get("variants")) or e["variant"] == v)
        arms.append(dict(c, variant=v, rate=r, low=lo, high=hi, reached=c["n"] >= need, cost=cost,
                         cost_per_conversion=(cost / c["k"]) if c["k"] and cost else None,
                         price_point=(d.get("price_points") or {}).get(v)))
    reached = all(a["reached"] for a in arms)
    days = None
    if x["launched_at"]:
        end = (x["completed_at"] or today())[:10]
        days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(x["launched_at"][:10])).days
    interim = x["status"] == "running" and not reached
    looks = x["looks"]
    if record_look and x["status"] == "running":
        looks += 1
        store.update("experiments", xid, {"looks": looks}, action="look")
    res = {"id": xid, "type": x["type"], "title": x["title"], "status": x["status"], "design": d, "arms": arms,
           "reached_planned_sample": reached, "interim": interim, "looks": looks, "days_running": days,
           "problems": problems, "registered_at": x["registered_at"], "launched_at": x["launched_at"],
           "hypothesis_id": x["hypothesis_id"], "segment_id": x["segment_id"],
           "funnel": _funnel(events), "sources": _sources(events, pm["denominator"]),
           "money": money(store, experiment_id=xid),
           "amendments": store.rows("SELECT at, change, reason FROM experiment_amendments WHERE experiment_id = ?", (xid,))}
    if all(a["n"] == 0 for a in arms) and any(a["unqualified_n"] or a["unknown_n"] for a in arms):
        res["outcome"] = "unreadable"
        res["reading"] = ("There is traffic, but none of it is recorded as qualified, so this says nothing about demand"
                          " from your target customer. Record which visitors were qualified, or run it on a qualified audience.")
    elif problems:
        res["outcome"], res["reading"] = "unreadable", "The counts are inconsistent. Fix the import before reading anything."
    elif x["type"] in MULTI_ARM:
        _read_multi(res, arms, rule, reached, looks)
    else:
        _read_single(res, arms[0], rule, reached, need)
    res["meaning"] = d["outcomes"].get(res["outcome"]) if res["outcome"] in ("success", "failure", "inconclusive") else None
    return res


def _read_single(res, a, rule, reached, need):
    if not reached:
        res["outcome"] = "not_enough_data"
        res["reading"] = "%d of the %d qualified %s the design calls for. Too early to conclude anything." % (
            a["n"], need, res["design"]["primary_metric"]["denominator"])
        if a["n"] and a["k"] == 0:
            res["reading"] += " Zero so far only shows the true rate is probably below %s." % stats.pct(stats.rule_of_three(a["n"]))
        return
    ok, bad = rule["success_at"], rule["fail_below"]
    if a["rate"] >= ok:
        res["outcome"] = "success"
    elif a["rate"] < bad:
        res["outcome"] = "failure"
    else:
        res["outcome"] = "inconclusive"
    res["reading"] = "%s against a success line of %s and a failure line of %s, both set before launch." % (
        stats.describe_rate(a["k"], a["n"]), stats.pct(ok), stats.pct(bad))
    if a["low"] < bad and a["high"] >= ok:
        res["fragile"] = True
        res["reading"] += (" The interval spans both lines, so a repeat of this test could land on the other side."
                           " Treat the result as fragile.")


def _read_multi(res, arms, rule, reached, looks):
    control = arms[0]
    alpha = float(rule.get("alpha", 0.05)) / max(1, len(arms) - 1)
    res["alpha_per_comparison"] = alpha
    comparisons = []
    for a in arms[1:]:
        if not control["n"] or not a["n"]:
            comparisons.append({"variant": a["variant"], "vs": control["variant"], "readable": False})
            continue
        t = stats.two_proportions(control["k"], control["n"], a["k"], a["n"], confidence=1 - alpha)
        c = {"variant": a["variant"], "vs": control["variant"], "readable": True, "diff": t["diff"], "ci": t["ci"],
             "relative_lift": t["relative_lift"], "p_value": t["p_value"], "approximation_ok": t["approximation_ok"],
             "significant": t["approximation_ok"] and t["p_value"] < alpha,
             "practical": abs(t["diff"]) >= rule["min_effect"]}
        if control["price_point"] is not None and a["price_point"] is not None and t["approximation_ok"] \
                and control["price_point"] != a["price_point"]:
            c["arc_elasticity"] = stats.arc_elasticity(control["price_point"], control["rate"], a["price_point"], a["rate"])
        comparisons.append(c)
    res["comparisons"] = comparisons
    if not reached:
        res["outcome"] = "not_enough_data"
        res["reading"] = ("Planned sample not reached (%s). This is look number %d before the planned sample. Every early"
                          " look raises the chance of a false winner, so no winner is declared." % (
                              ", ".join("%s: %d of %d" % (a["variant"], a["n"], res["design"]["stopping_rule"]["min_denominator_per_variant"])
                                        for a in arms), looks))
        return
    winners = [c for c in comparisons if c["readable"] and c["significant"] and c["practical"]]
    if winners:
        best = max(winners, key=lambda c: abs(c["diff"]))
        res["outcome"] = "success"
        res["winner"] = best["variant"] if best["diff"] > 0 else control["variant"]
        res["reading"] = "%s beats %s by %s points (interval %s to %s, p = %.3f), larger than the minimum effect of %s set before launch." % (
            res["winner"], best["vs"] if best["diff"] > 0 else best["variant"], _pts(abs(best["diff"])),
            _pts(best["ci"][0]), _pts(best["ci"][1]), best["p_value"], _pts(rule["min_effect"]))
    elif any(c["readable"] and not c["approximation_ok"] for c in comparisons):
        res["outcome"] = "inconclusive"
        res["reading"] = "Too few conversions in at least one version for a significance test. No winner."
    elif any(c["readable"] and c["significant"] for c in comparisons):
        res["outcome"] = "inconclusive"
        res["reading"] = "A statistically detectable difference, but smaller than the minimum effect worth acting on. No winner."
    else:
        res["outcome"] = "failure" if all(c["readable"] and abs(c["ci"][0]) < rule["min_effect"] and abs(c["ci"][1]) < rule["min_effect"]
                                          for c in comparisons) else "inconclusive"
        res["reading"] = ("No difference of the size you cared about: the whole interval sits inside the minimum effect."
                          if res["outcome"] == "failure" else
                          "No reliable difference at this sample. That is not proof the versions are equal.")
    if looks > 1:
        res["reading"] += " Note: this test was read %d times while running; p-values assume one planned reading." % looks


def _pts(v):
    return "%.1f" % (v * 100.0)


def _funnel(events):
    out = {}
    for e in events:
        row = out.setdefault((e["variant"], e["event"]), {"variant": e["variant"], "event": e["event"],
                                                           "qualified": 0, "unqualified": 0, "unknown": 0})
        row["qualified" if e["qualified"] == 1 else ("unqualified" if e["qualified"] == 0 else "unknown")] += e["count"]
    return sorted(out.values(), key=lambda r: (r["variant"], -r["qualified"], r["event"]))


def _sources(events, denominator):
    out = {}
    for e in events:
        if e["event"] != denominator:
            continue
        row = out.setdefault(e["traffic_source"] or "(not recorded)", {"qualified": 0, "unqualified": 0, "unknown": 0, "cost": 0.0})
        row["qualified" if e["qualified"] == 1 else ("unqualified" if e["qualified"] == 0 else "unknown")] += e["count"]
        row["cost"] += e["cost"]
    return out


def complete(store, xid, conclusion, abandoned=False):
    x = store.get("experiments", xid, "experiment")
    if x["status"] not in ("running", "designed"):
        raise StoreError("%s is already %s" % (xid, x["status"]))
    if not (conclusion or "").strip():
        raise StoreError("closing an experiment needs a written conclusion, including when it failed")
    store.update("experiments", xid, {"status": "abandoned" if abandoned else "completed", "completed_at": now(),
                                      "conclusion": conclusion}, action="abandon" if abandoned else "complete")


def plan_sample(xtype, baseline, min_effect=None, margin=None, alpha=0.05, power=0.8):
    """How many qualified observations a design needs. Returns a dict with the number and what it buys."""
    if xtype in MULTI_ARM:
        n = stats.sample_size_two_proportions(baseline, min_effect, alpha, power)
        return {"per_variant": n, "says": "%d qualified observations in each version to detect a %s point change from %s"
                                           " with %d%% power." % (n, _pts(abs(min_effect)), stats.pct(baseline), round(power * 100))}
    n = stats.sample_size_one_proportion(baseline, margin)
    return {"per_variant": n, "says": "%d qualified observations to estimate a rate near %s to within plus or minus %s points."
                                       % (n, stats.pct(baseline), _pts(margin))}
