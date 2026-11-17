"""The validation report, the status line and the export for founder-validate. Standard library only.

The report is rebuilt from the store every time. Nothing in it is written by
hand, every conclusion carries the ids of the evidence behind it, and synthetic
material is fenced off and labelled wherever it appears.
"""

import csv
import json
import math
import os

import fv_stats as stats
from fv_score import CONTRADICTED, LEVELS, MIN_COMPARABLE, THRESHOLDS, UNIT_NAMES
from fv_store import CATEGORIES, KNOWLEDGE

FIVE = [
    ("Is the problem real?", ("problem",)),
    ("Do the right customers want this solution?", ("segment", "solution", "demand")),
    ("Will they actually pay for it?", ("behavior", "payment")),
    ("Can we acquire and serve them profitably?", ("economics",)),
]
SIM = "SIMULATED"


def clean(obj):
    """Make a snapshot JSON-safe: sets become lists, infinities and NaN become null."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in (sorted(obj, key=str) if isinstance(obj, set) else obj)]
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    return obj


def _ids(items):
    live = [e["id"] for e in items if not e["retracted_at"]]
    return (" [" + ", ".join(live) + "]") if live else " [no evidence]"


def _weakest(snap, dims):
    by = {d["dimension"]: d for d in snap["dimensions"]}
    order = [CONTRADICTED] + LEVELS
    return min((by[d] for d in dims), key=lambda d: order.index(d["level"]))


def _cell(text):
    return " ".join(str(text if text is not None else "").replace("|", "/").split())


def status_text(snap):
    """A short, plain status for the terminal."""
    c = snap["counts"]
    L = ["%s: %s" % (snap["project"], snap["verdict"]["decision"]), "  " + snap["verdict"]["text"], "",
         "  Real evidence:     %d people interviewed, %d valid survey answers, %d qualified actions on a primary metric, %d paying customers" % (
             c["real_people_interviewed"], c["valid_survey_responses"], c["qualified_actions"], c["paying_customers"]),
         "  Simulated (no weight): %d synthetic answers" % c["synthetic_responses"], ""]
    for d in snap["dimensions"]:
        L.append("  %-10s %s%s" % (d["dimension"], d["level"], " (contested)" if d["contested"] else ""))
    r = snap["recommendation"]
    L.append("")
    if r.get("question"):
        L += ["  Most important unanswered question (%s): %s" % (r["hypothesis_id"], r["question"]),
              "  Cheapest credible next step: %s (%s, about %s days)" % (r["experiment"]["name"], r["experiment"]["cost"], r["experiment"]["days"])]
        if r.get("prerequisite"):
            L.append("  First: " + r["prerequisite"])
        if r.get("do_not_build"):
            L.append("  " + r["do_not_build"])
    else:
        L.append("  " + r["note"])
    return "\n".join(L) + "\n"


def _dimension_block(d):
    L = ["**%s %s%s.**%s" % (d["question"], d["level"], " (contested)" if d["contested"] else "", _ids(d["items"])), ""]
    if d["support"] or d["contra"]:
        L += ["| side | kind of evidence | real units | counted toward the grade |", "| --- | --- | ---: | ---: |"]
        for side, cats in (("for", d["support"]), ("against", d["contra"])):
            for cat in sorted(cats):
                c = cats[cat]
                L.append("| %s | %s: %s | %d | %d %s |" % (side, cat, CATEGORIES[cat], c["units"], c["strong_units"], UNIT_NAMES[cat]))
        L.append("")
    for e in d["items"]:
        if e["retracted_at"]:
            continue
        tag = ("%s, " % SIM) if e["category"] == "B" else ("ASSUMPTION, " if e["category"] == "A" else "")
        L.append("- %s (%s%s, %s, %s): %s. _%s_" % (e["id"], tag, e["category"], e["stance"], e["collected_on"],
                                                  _cell(e["summary"]).rstrip("."), e["resolved"]))
    if d["items"]:
        L.append("")
    if d["limitations"]:
        L += ["Known limitations:"] + ["- %s" % x for x in d["limitations"]] + [""]
    if d["missing"]:
        L += ["Missing:"] + ["- %s" % x for x in d["missing"]] + [""]
    return L


def report(snap):
    by = {d["dimension"]: d for d in snap["dimensions"]}
    c = snap["counts"]
    v, rec = snap["verdict"], snap["recommendation"]
    L = ["# %s · Market validation report" % snap["project"], "",
         "_Generated %s from the evidence store. Grading rules %s. Rebuilt on every run; never edited by hand._" % (
             snap["generated_at"], snap["rules_version"]), ""]

    # 1 ------------------------------------------------------------------------
    L += ["## 1. Executive summary", "", "**Recommendation: %s.** %s" % (v["decision"], v["text"]), ""]
    L += ["| the question | status | weakest link |", "| --- | --- | --- |"]
    for q, dims in FIVE:
        w = _weakest(snap, dims)
        L.append("| %s | %s | %s%s |" % (q, w["level"], w["dimension"], _ids(w["items"])))
    L.append("| What is the cheapest next experiment that would materially reduce our uncertainty? | %s | %s |" % (
        rec["experiment"]["name"] if rec.get("question") else "none open", rec.get("hypothesis_id") or ""))
    L += ["", "What this rests on:", "", "| | count | weight in the grades |", "| --- | ---: | --- |",
          "| Real people interviewed | %d | counted |" % c["real_people_interviewed"],
          "| Valid real survey answers | %d | counted |" % c["valid_survey_responses"],
          "| Qualified actions on a primary metric | %d | counted |" % c["qualified_actions"],
          "| Paying customers (net) | %d | counted |" % c["paying_customers"],
          "| Synthetic answers (%s) | %d | none, at any number |" % (SIM, c["synthetic_responses"]), ""]

    # 2, 3 ---------------------------------------------------------------------
    L += ["## 2. Business concept", ""]
    for k in snap["concepts"]:
        price = (" Price point: %s %s." % (k["price_point"], k["currency"] or "")) if k["price_point"] is not None else ""
        L += ["**%s (%s).** %s%s" % (k["name"], k["id"], k["description"], price), ""]
    L += ["## 3. Target customer", ""]
    if not snap["segments"]:
        L += ["No segment defined yet.", ""]
    for s in snap["segments"]:
        L += ["- **%s (%s).** %s Screening criteria: %s. Basis: %s%s." % (
            s["name"], s["id"], s["definition"], s["criteria"] or "none written", s["basis"],
            (" (%s)" % s["basis_note"]) if s["basis_note"] else "")]
    L += [""] + _dimension_block(by["segment"])

    # 4 ------------------------------------------------------------------------
    L += ["## 4. Problem evidence", ""] + _dimension_block(by["problem"])

    # 5 ------------------------------------------------------------------------
    L += ["## 5. Market research", "", "External sources. They describe the market in general, not your customers.", ""]
    other = [s for s in snap["research_sources"] if s["kind"] != "competitor_price"]
    if not other:
        L += ["None recorded.", ""]
    for s in other:
        L.append("- %s (%s): [%s](%s), %s, accessed %s. %s" % (s["id"], s["kind"], _cell(s["title"]), s["url"],
                                                              s["publisher"] or "publisher not recorded", s["accessed_on"], _cell(s["excerpt"])))
    L.append("")

    # 6 ------------------------------------------------------------------------
    L += ["## 6. Synthetic customer insights", "",
          "> **%s. Not customers, not a sample, not a forecast.** Everything in this section came from a language model"
          " playing profiles. It is here to generate questions. It has no weight in any grade above." % SIM, ""]
    if not snap["synthetic_runs"]:
        L += ["No synthetic runs.", ""]
    for r in snap["synthetic_runs"]:
        L += ["**Run %s** (%s). Model: %s. Prompt: %s. Seed: %s. %d profiles, %d repeat(s), %d answers filed. %s" % (
            r["id"], r["kind"], r["model"], r["prompt_version"], r["seed"], r["n_personas"], r["repeats"], r["responses"],
            r["persona_method"]), ""]
        t = r["tally"]
        if not t:
            continue
        for arm, block in sorted((t.get("concept") or {}).items()):
            w = block["wobble"]
            L.append("Arm %s, reasons simulated profiles gave to reject: %s.%s" % (
                arm, ", ".join("%s (%d)" % (x["code"], x["profiles"]) for x in block["reasons_to_reject"]) or "none",
                (" Between repeats, %d of %d profiles changed stance." % (w["changed_answer"], w["profiles_repeated"])) if w else ""))
            for o in block["objections"][:6]:
                L.append("- (simulated objection) %s" % _cell(o))
            L.append("")
        if t.get("panel"):
            L += ["Imported panel: %d simulated said buy, %d said pass. %s" % (t["panel"]["said_buy"], t["panel"]["said_pass"],
                                                                             t["panel"]["note"]), ""]
        if t["questions_for_real_customers"]:
            L += ["Questions this run says to take to real customers:"] + ["- %s" % _cell(q) for q in t["questions_for_real_customers"][:10]] + [""]

    # 7 ------------------------------------------------------------------------
    iv = snap["interviews"]
    L += ["## 7. Actual customer interviews", "", iv["generalise"], ""]
    if iv["participants"]:
        L += ["%d interviews with %d people. By segment: %s. By role: %s. By guide: %s." % (
            iv["interviews"], iv["participants"], _kv(iv["by_segment"]), _kv(iv["by_role"]), _kv(iv["by_guide"])), "",
            "| theme | people | describing past behaviour | note |", "| --- | ---: | ---: | --- |"]
        for t in iv["themes"]:
            L.append("| %s | %d of %d | %d | %s |" % (_cell(t["theme"]), t["participants"], t["of"], t["with_past_behaviour"],
                                                    "outlier: one person" if t["outlier"] else ""))
        L.append("")
        for t in iv["themes"]:
            for q in t["quotes"][:3]:
                L.append('- Verbatim, %s (%s, extract %s): "%s"' % (q["participant"], q["kind"], q["id"], _cell(q["text"])))
            for s in t["summaries"][:3]:
                L.append("- Summary by %s, not a quote, %s (%s, extract %s): %s" % (
                    "AI" if s["author"] == "ai" else "the founder", s["participant"], s["kind"], s["id"], _cell(s["text"])))
        L.append("")
    if snap["recruitment"]:
        L += ["Recruitment, counted from participant records:", ""]
        for r in snap["recruitment"]:
            L.append("- %s: %d interviewed%s. %s" % (r["segment"], r["interviewed"],
                                                    (" of a target of %s" % r["target"]) if r["target"] else "", _kv(r["counts"])))
        L.append("")

    # 8 ------------------------------------------------------------------------
    L += ["## 8. Actual survey findings", ""]
    if not snap["surveys"]:
        L += ["No surveys.", ""]
    for s in snap["surveys"]:
        L += ["**%s (%s).** Population: %s. Reached via: %s. Fielded %s to %s. %d received, %d valid. Excluded: %s." % (
            s["title"], s["id"], s["population"], s["distributed_via"] or "not recorded", s["fielded_from"] or "?",
            s["fielded_to"] or "?", s["received"], s["valid"], _kv(s["excluded"]) or "none"), "",
            "Representative? " + s["representative"], ""]
        for heading, kinds in (("Reported past behaviour", ("behavioral", "screening")),
                               ("Stated preferences (what people say, not what they do)", ("stated", "pricing")),
                               ("Who answered", ("demographic",))):
            qs = [q for q in s["questions"] if q["kind"] in kinds]
            if not qs:
                continue
            L += ["_%s_" % heading, ""]
            for q in qs:
                if q["type"] in ("single", "multi"):
                    L.append("- %s (n = %d): %s" % (_cell(q["text"]), q["n"], "; ".join(
                        "%s %s" % (o["option"], stats.describe_rate(o["k"], q["n"])) for o in q["options"])))
                elif q["type"] == "number" and q["n"]:
                    L.append("- %s (n = %d): median %s, middle half %s to %s" % (_cell(q["text"]), q["n"], q["median"], q["q1"], q["q3"]))
            L.append("")

    # 9 ------------------------------------------------------------------------
    L += ["## 9. Behavioral experiments", ""]
    if not snap["experiments"]:
        L += ["No experiments.", ""]
    for x in snap["experiments"]:
        d = x["design"]
        L += ["**%s: %s** (%s, %s). Design registered %s, launched %s. Looks while running: %d." % (
            x["id"], x["title"], x["type"].replace("_", " "), x["status"], x["registered_at"][:10],
            (x["launched_at"] or "not yet")[:10], x["looks"]),
            "Population: %s Qualified means: %s Primary metric: %s over %s. Stopping rule: %d qualified per variant or %d days." % (
                _dot(d["population"]), _dot(d["qualification"]), d["primary_metric"]["event"], d["primary_metric"]["denominator"],
                d["stopping_rule"]["min_denominator_per_variant"], d["stopping_rule"]["max_days"]), ""]
        if x["launched_at"]:
            L += ["| variant | qualified result | left out (unqualified / unknown) | cost per conversion |", "| --- | --- | ---: | ---: |"]
            for a in x["arms"]:
                L.append("| %s%s | %s | %d / %d | %s |" % (
                    a["variant"], (" at %s" % a["price_point"]) if a["price_point"] is not None else "",
                    stats.describe_rate(a["k"], a["n"]) if a["k"] <= a["n"] else "inconsistent counts",
                    a["unqualified_n"], a["unknown_n"], ("%.2f" % a["cost_per_conversion"]) if a["cost_per_conversion"] else "n/a"))
            L += ["", "Outcome: **%s**. %s%s" % (x["outcome"].replace("_", " "), x["reading"],
                                                (" What this means: %s" % x["meaning"]) if x["meaning"] else ""), ""]
            m = x["money"]
            if m["transactions"]:
                L += ["Money: %d paying customer(s) net, %d cancelled or refunded, %d repeat. Net revenue %s." % (
                    m["n_payers"], len(m["cancelled_or_refunded"]), len(m["repeat_payers"]),
                    ("%.2f %s" % (m["net_revenue"], m["currencies"][0])) if m["net_revenue"] is not None and m["currencies"] else "in mixed currencies"), ""]
        for am in x["amendments"]:
            L.append("- Amended %s: %s (%s)" % (am["at"][:10], _cell(am["change"]), _cell(am["reason"])))
        if x["amendments"]:
            L.append("")
    L += _dimension_block(by["demand"]) + _dimension_block(by["behavior"])

    # 10 -----------------------------------------------------------------------
    p = snap["pricing"]
    L += ["## 10. Pricing evidence", "",
          "Six kinds of price evidence, weakest first. They are shown side by side and never averaged.", ""]
    if not p["layers"]:
        L += ["No price evidence of any kind yet.", ""]
    for layer in p["layers"]:
        L.append("- **%d. %s** (category %s%s%s): %s" % (
            layer["layer"], layer["name"], layer["category"], ", %s" % SIM if layer["category"] == "B" else "",
            (", %s" % layer["ref"]) if layer.get("ref") else "", _price_line(layer)))
    L.append("")
    if p["role_gap"]:
        L += ["Not yet interviewed: %s. Liking a product and controlling the money for it are different people in most"
              " B2B purchases." % " and ".join(r.replace("_", " ") for r in p["role_gap"]), ""]
    L += _dimension_block(by["payment"])

    # 11 -----------------------------------------------------------------------
    L += ["## 11. Competitive environment", ""]
    comp = [s for s in snap["research_sources"] if s["kind"] == "competitor_price"]
    if not comp:
        L += ["No competitor prices recorded here. See founder/competitors.md if founder-competitors has run.", ""]
    for s in comp:
        L.append("- %s: [%s](%s) charges %s %s%s (accessed %s)." % (
            s["id"], _cell(s["title"]), s["url"], s["price"], s["currency"] or "",
            (" for %s" % _cell(s["price_includes"])) if s["price_includes"] else "", s["accessed_on"]))
    L += ["", "## 12. Financial viability", ""] + _dimension_block(by["economics"])
    if by["economics"].get("projection"):
        pr = by["economics"]["projection"]
        L += ["Projection from founder/numbers.json (an assumption until measured): each %s contributes %.2f at a price of"
              " %.2f; margin at plan %.0f%%; year 1 operating profit %s." % (
                  pr["unit"], pr["contribution"], pr["price"], pr["margin_at_plan"] * 100, "{:,.0f}".format(pr["year1_profit"])), ""]
    L += _dimension_block(by["solution"])

    # 13 -----------------------------------------------------------------------
    L += ["## 13. Contradictory evidence", "", "Everything that points against the idea. Nothing is removed from this list.", ""]
    contra = [e for d in snap["dimensions"] for e in d["items"] if e["stance"] == "contradicts" and not e["retracted_at"]]
    retracted = [e for d in snap["dimensions"] for e in d["items"] if e["retracted_at"]]
    failed = [x for x in snap["experiments"] if x.get("outcome") == "failure"]
    for e in contra:
        L.append("- %s (%s, %s, against claim %s): %s. _%s_" % (e["id"], e["category"], e["dimension"], e["claim_id"],
                                                               _cell(e["summary"]).rstrip("."), e["resolved"]))
    for x in failed:
        L.append("- Experiment %s failed its pre-set line: %s" % (x["id"], x["reading"]))
    for x in snap["interviews"]["contradictions"]:
        L.append("- Interview extract %s (%s): %s" % (x["id"], "verbatim" if x["verbatim"] else "summary", _cell(x["text"])))
    for e in retracted:
        L.append("- Retracted %s on %s: %s. Reason: %s" % (e["id"], e["retracted_at"][:10], _cell(e["summary"]), _cell(e["retract_reason"])))
    if not (contra or failed or retracted or snap["interviews"]["contradictions"]):
        L.append("None recorded. With little real evidence collected, that is absence of testing, not absence of problems.")
    L.append("")

    # 14 -----------------------------------------------------------------------
    L += ["## 14. Critical unanswered questions", "", "| id | area | hypothesis | priority | status | real evidence items |",
          "| --- | --- | --- | ---: | --- | ---: |"]
    for h in snap["hypotheses"]:
        if not h["answered"]:
            L.append("| %s | %s | %s | %.1f | %s%s | %d |" % (h["id"], h["area"], _cell(h["statement"]), h["priority"], h["status"],
                                                           ", explored synthetically only" if h["explored_synthetically"] and not h["real_items"] else "",
                                                           h["real_items"]))
    L += ["", "Priority = impact if false x uncertainty / average of cost and time to test (each 1 to 5).", ""]

    # 15 -----------------------------------------------------------------------
    L += ["## 15. Validation status", "", "| question | status | evidence |", "| --- | --- | --- |"]
    for d in snap["dimensions"]:
        L.append("| %s | %s%s | %s |" % (d["question"], d["level"], " (contested)" if d["contested"] else "", _ids(d["items"]).strip()))
    L += ["", "There is deliberately no overall score. A single number would hide which of these is missing.", ""]

    # 16 -----------------------------------------------------------------------
    L += ["## 16. Recommended next experiments", ""]
    if rec.get("question"):
        e = rec["experiment"]
        L += ["**Most important unanswered question (%s):** %s" % (rec["hypothesis_id"], rec["question"]), "", rec["why"],
              ("If it is false: %s" % rec["if_false"]) if rec["if_false"] else "", ""]
        if rec.get("prerequisite"):
            L += ["**First:** " + rec["prerequisite"], ""]
        L += ["**Cheapest credible experiment: %s.**" % e["name"], "",
              "- Who: %s" % e["population"], "- How: %s" % e["method"], "- Primary metric: %s" % e["metric"],
              "- Sample or stopping rule: %s" % e["stop"], "- Cost: %s. Time: about %s days." % (e["cost"], e["days"]),
              "- If it supports: %s" % e["outcomes"]["supports"], "- If it contradicts: %s" % e["outcomes"]["contradicts"],
              "- If unclear: %s" % e["outcomes"]["unclear"], ""]
        if rec.get("do_not_build"):
            L += ["**%s**" % rec["do_not_build"], ""]
    else:
        L += [rec["note"], ""]

    # 17 -----------------------------------------------------------------------
    L += ["## 17. Go / Conditional Go / No-Go", "", "**%s.** %s" % (v["decision"], v["text"]), ""]
    if v["conditions"]:
        L += ["Open before a Go: " + ", ".join(v["conditions"]) + ".", ""]

    # appendices ---------------------------------------------------------------
    L += ["## Appendix A. Claims register", ""]
    for cl in snap["claims"]:
        sup, con = cl["supporting"], cl["contradicting"]
        strongest = cl["strongest_category"]
        L += ["### %s. %s" % (cl["id"], cl["description"]), "",
              "- Question it bears on: %s. Hypothesis: %s. Segment: %s." % (cl["dimension"], cl["hypothesis_id"] or "none", cl["segment"] or "not set"),
              "- Evidence category (strongest supporting): %s." % (("%s, %s (%s)" % (strongest, CATEGORIES[strongest], KNOWLEDGE[strongest])) if strongest else "none"),
              "- Confidence (computed): %s%s. Limitations: %s" % (cl["confidence"], ", contested" if cl["contested"] else "", cl["limitations"] or "none recorded"),
              "- Business implications: %s" % (cl["implications"] or "not written"),
              "- Recommended next experiment: %s" % (cl["next_experiment"] or "not written")]
        for side, items in (("Supporting", sup), ("Contradicting", con)):
            for e in items:
                L.append("- %s %s%s: category %s; source %s; method %s; collected %s; sample: %s. %s%s" % (
                    side, e["id"], " (RETRACTED: %s)" % e["retract_reason"] if e["retracted_at"] else "", e["category"],
                    json.dumps(e["ref"], sort_keys=True) if e["ref"] else "none (assumption)", e["method"], e["collected_on"],
                    e["resolved"], _cell(e["summary"]), (" Limits: %s" % e["limitations"]) if e["limitations"] else ""))
        L.append("")
    cal = snap["calibration"]
    L += ["## Appendix B. Predictions against reality", "", cal["statement"], ""]
    for pr in cal["pairs"]:
        L += ["**%s vs %s.** Predicted (%s, %s): %s of \"%s\". Actual: %s of \"%s\". %s" % (
            pr["prediction_id"], pr["experiment_id"], pr["source"], pr["model"] or "no model", stats.pct(pr["predicted"]),
            pr["predicted_measure"], stats.describe_rate(pr["actual_k"], pr["actual_n"]) if pr["actual"] is not None else "unreadable",
            pr["actual_measure"], "Marked comparable: %s." % pr["comparable_note"] if pr["comparable"] else
            "Marked NOT comparable: %s." % pr["comparable_note"]),
            "These two numbers are not averaged. Possible reasons they differ:"] + ["- %s" % r for r in pr["possible_reasons"]] + [""]
    for row in cal["summary"]:
        L.append("- %s / %s / %s: %s" % (row["source"], row["model"] or "no model", row["prediction_type"], row["says"]))
    L += ["", "## Appendix C. How to read this report", "",
          "- **Seven kinds of evidence.** " + "; ".join("%s = %s" % (k, v.lower()) for k, v in sorted(CATEGORIES.items())) + ".",
          "- **A and B never count.** An assumption or a simulated answer can suggest what to test. It cannot move a grade,"
          " however many there are.",
          "- **Saying is not doing.** Opinions and stated intentions are capped at weak. Past behaviour, observed actions"
          " and payments can go higher.",
          "- **Thresholds are conventions.** Moderate and strong need " + "; ".join(
              "%s: %s and %s %s" % (k, v[1], v[2], UNIT_NAMES[k]) for k, v in sorted(THRESHOLDS.items()) if v[1]) +
          ". They are cautious rules of thumb, not statistical proof.",
          "- **Samples are not the market.** Counts describe the people reached. Nothing here claims a sample is representative.",
          "- **Intervals.** A percentage is shown with a 95% interval: the range the true rate plausibly sits in given the sample.",
          "- **Calibration.** No figure is computed until %d comparable prediction/result pairs exist." % MIN_COMPARABLE,
          "- **Audit trail.** %d entries, hash chain %s." % (snap["audit"]["entries"], "intact" if snap["audit"]["ok"] else
                                                          "BROKEN at entry %s: the record was altered outside the tool" % snap["audit"]["first_bad"]),
          ""]
    return "\n".join(x for x in L if x is not None) + "\n"


def _kv(d):
    return ", ".join("%s %s" % (k, v) for k, v in sorted(d.items(), key=lambda kv: str(kv[0])))


def _dot(s):
    s = _cell(s)
    return s if s.endswith(".") else s + "."


def _price_line(layer):
    bits = [layer["reading"]]
    vw = layer.get("van_westendorp")
    if vw and vw["points"].get("PMC") is not None and vw["points"].get("PME") is not None:
        bits.append("Van Westendorp range %.2f to %.2f from %d answers (exploratory)." % (vw["points"]["PMC"], vw["points"]["PME"], vw["n"]))
    gg = layer.get("gabor_granger")
    if gg:
        bits.append("Gabor-Granger: stated revenue peaks at %.2f across %d answers (exploratory, stated)." % (gg["revenue_max_price"], gg["n"]))
    if layer["layer"] == 2:
        bits.append("; ".join("%s: %s %s" % (i["participant"], i["amount"], i["currency"] or "") for i in layer["items"][:8]) + ".")
    if layer["layer"] == 4:
        bits.append("; ".join("%s %s %s" % (_cell(i["title"]), i["price"], i["currency"] or "") for i in layer["items"][:8]) + ".")
    if layer["layer"] == 5:
        bits.append("; ".join("at %s: %s" % (a["price"], stats.describe_rate(a["k"], a["n"])) for a in layer["arms"]) + ".")
        for cmp_ in layer.get("comparisons") or []:
            if cmp_.get("arc_elasticity") is not None:
                bits.append("Arc elasticity between the two prices: %.2f." % cmp_["arc_elasticity"])
    if layer["layer"] == 6:
        bits.append("%d paying customer(s), %d repeat; by price: %s." % (
            layer["n"], layer["repeat_payers"], _kv(layer["payers_by_price"]) or "no price points recorded"))
    return " ".join(bits)


EXPORT_TABLES = ["concepts", "segments", "hypotheses", "hypothesis_versions", "claims", "evidence", "research_sources",
                 "syn_runs", "syn_personas", "syn_responses", "participants", "interviews", "interview_extracts", "surveys",
                 "survey_responses", "experiments", "experiment_amendments", "behavior_events", "transactions", "predictions",
                 "outcomes", "audit_log"]
EXPORT_FAMILY = {"syn_runs": "synthetic", "syn_personas": "synthetic", "syn_responses": "synthetic",
                 "participants": "real_respondents", "interviews": "real_respondents", "interview_extracts": "real_respondents",
                 "surveys": "real_respondents", "survey_responses": "real_respondents",
                 "experiments": "behaviour", "experiment_amendments": "behaviour", "behavior_events": "behaviour",
                 "transactions": "transactions"}


def export(store, snap, out_dir):
    """Write every table as CSV (grouped by data family), the snapshot as JSON and the report. Returns file count."""
    n = 0
    for table in EXPORT_TABLES:
        folder = os.path.join(out_dir, EXPORT_FAMILY.get(table, "record"))
        os.makedirs(folder, exist_ok=True)
        rows = store.rows("SELECT * FROM %s" % table)
        cols = store._columns(table)
        with open(os.path.join(folder, table + ".csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
        n += 1
    with open(os.path.join(out_dir, "snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump(clean(snap), fh, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, "validation-report.md"), "w", encoding="utf-8") as fh:
        fh.write(report(snap))
    return n + 2
