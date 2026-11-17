"""The synthetic customer lab for founder-validate. Standard library only, no network.

Simulated profiles are a research instrument: a cheap way to find objections,
segments and questions you had not thought of BEFORE talking to real people.
They are not respondents. This module deals the profiles, writes one brief per
profile per stage for a sub-agent to answer, files the answers in the synthetic
tables and tallies them. It never answers for a profile.

What makes it a lab and not a cheerleader:
  - nine fixed dispositions (skeptics, the satisfied, people without the
    problem...) dealt by quota, with enthusiasts capped;
  - the problem stage never shows the solution;
  - the offer is refused if it contains promotional language;
  - every profile in a comparison sees the same brief except the one thing
    being compared (the arm), assigned by a seeded shuffle;
  - model, prompt version, seed, repeats and assumptions are frozen in the run
    record; repeated runs measure how much the answers wobble;
  - the tally produces objections, questions and hypotheses. It does not
    produce a conversion rate, and nothing here can raise a validation level.
"""

import json
import os
import random
import re

from fv_store import StoreError, canonical, now, sha256_text

ARCHETYPES = [
    ("enthusiast", "Actively looking for a fix",
     "This situation bothers you often and you have looked for something better. You still need an offer to be credible."),
    ("skeptic", "Has heard it all before",
     "You have heard promises like this before. You assume a new offer will not deliver until you are shown otherwise."),
    ("price_sensitive", "Watches every cost",
     "You weigh every purchase against the cheapest way of getting by, including doing nothing."),
    ("satisfied", "Happy with what they use today",
     "What you do today works well enough. Switching has to earn its trouble."),
    ("no_problem", "Does not have the problem",
     "The difficulty other people describe in this situation rarely or never comes up for you."),
    ("high_power", "Money is not the constraint",
     "You can easily afford things like this. Time, trust and fit decide, not price."),
    ("change_averse", "Dislikes switching",
     "You keep the same habits and tools for years and avoid anything that needs setting up or learning."),
    ("influencer", "Influences the purchase, does not pay",
     "You would use it or recommend it, but someone else controls the money and makes the final call."),
    ("tried_before", "Tried something similar",
     "You have already tried or paid for something similar. It left a mark, and you compare everything new with it."),
]
ARCHETYPE_IDS = [a[0] for a in ARCHETYPES]
MAX_ENTHUSIAST = 0.2
MIN_RESISTANT = 0.3  # skeptic + satisfied + no_problem
MIN_ARCHETYPES = 6
STAGES = ("problem", "concept")
STANCES = ("would_seek_out", "interested", "indifferent", "skeptical", "rejects")
REASONS = ("price", "habit", "no_need", "trust", "quality", "effort", "timing", "not_my_decision", "fit", "other")
EXPERIENCES = ("often", "sometimes", "rarely", "never")
PROMO = re.compile(r"\b(best|revolutionary|amazing|game[- ]chang\w+|world[- ]class|effortless(ly)?|incredible|unbeatable|"
                   r"cutting[- ]edge|ultimate|perfect|guaranteed results|must[- ]have|life[- ]changing|seamless(ly)?|"
                   r"number one|#1|10x|magic(al)?)\b|!", re.I)

PROBLEM_BRIEF = """You are a SIMULATED person on a research panel. A founder is trying to learn whether a problem is real before building anything. You are not being sold to, and no product is shown. A polite or encouraging answer is worthless here: most situations are not a problem for most people. Answer only as this person.

=== WHO YOU ARE ===
{card}
Your disposition: {disposition}
=== END ===

=== THE SITUATION BEING STUDIED ===
{situation}
=== END ===

Describe how this situation actually goes for {name}. Stay consistent with the disposition above. Do not invent a product, and do not guess what the founder hopes to hear.

Create the file {out} with your file-writing tool containing ONLY this JSON, no markdown fence:
{{
  "id": "{id}",
  "stage": "problem",
  "experiences_problem": one of {experiences},
  "last_time": "the most recent time this came up for you and what happened, or empty if never",
  "current_solution": "what you do about it today (including nothing)",
  "cost_of_problem": "what it costs you in money, time or annoyance, in your own words",
  "if_nothing_changes": "what happens if you never fix it",
  "severity": a whole number 1 (do not care) to 5 (would pay today to be rid of it),
  "paid_to_solve_before": true or false,
  "questions_for_real_people": ["one or two things a founder should ask real people like you, to check you were simulated right"]
}}
"""

CONCEPT_BRIEF = """You are a SIMULATED person on a research panel. A founder wants to find the weak points in an offer before spending money. Agreeable answers are worthless: most people do not buy most things. Answer only as this person, with this person's money, habits and doubts.

=== WHO YOU ARE ===
{card}
Your disposition: {disposition}
=== END ===

=== WHAT YOU ALREADY HAVE AVAILABLE ===
{alternatives}
=== END ===

=== THE OFFER (plain description, you see it for the first time) ===
{offer}
{price_line}
=== END ===

=== THE MOMENT ===
{scenario}
=== END ===

Decide as {name} would in that moment. Do not invent facts about the offer beyond what is written. Compare it honestly with what you already have.

Create the file {out} with your file-writing tool containing ONLY this JSON, no markdown fence:
{{
  "id": "{id}",
  "stage": "concept",
  "arm": "{arm}",
  "stance": one of {stances},
  "reason_code": one of {reasons},
  "reason": "why, in one or two sentences, in your own voice",
  "main_objection": "the doubt that weighs most",
  "adoption_barrier": "what would physically or practically stop you, even if you liked it",
  "alternative_i_would_use": "what you would do instead",
  "purchase_trigger": "the event that would make you act, or empty",
  "other_use": "a different use or user for this that the founder may not have considered, or empty",
  "who_decides": "who makes the buying decision in your case",
  "who_pays": "whose money it is",
  "price_too_cheap": a number or null,
  "price_cheap": a number or null,
  "price_expensive": a number or null,
  "price_too_expensive": a number or null,
  "questions_for_real_people": ["one or two things the founder must check with real people before believing you"]
}}
"""
PROMPT_VERSION = "lab-1:" + sha256_text(PROBLEM_BRIEF + CONCEPT_BRIEF)[:10]


def _quota(weights, n):
    total = float(sum(weights)) or 1.0
    raw = [n * w / total for w in weights]
    counts = [int(r) for r in raw]
    order = sorted(range(len(weights)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    return counts


def archetype_mix(customer):
    """The share of each disposition. Defaults to equal shares; a custom mix cannot stack the panel with fans."""
    mix = customer.get("archetype_mix")
    if not mix:
        return {a: 1.0 / len(ARCHETYPE_IDS) for a in ARCHETYPE_IDS}
    unknown = set(mix) - set(ARCHETYPE_IDS)
    if unknown:
        raise StoreError("unknown archetype: %s (use %s)" % (", ".join(sorted(unknown)), ", ".join(ARCHETYPE_IDS)))
    total = float(sum(mix.values()))
    if total <= 0:
        raise StoreError("archetype_mix has no weight")
    shares = {a: mix.get(a, 0) / total for a in ARCHETYPE_IDS}
    if sum(1 for v in shares.values() if v > 0) < MIN_ARCHETYPES:
        raise StoreError("the panel needs at least %d different dispositions" % MIN_ARCHETYPES)
    if shares["enthusiast"] > MAX_ENTHUSIAST + 1e-9:
        raise StoreError("enthusiasts are capped at %d%% of the panel" % (MAX_ENTHUSIAST * 100))
    if shares["skeptic"] + shares["satisfied"] + shares["no_problem"] < MIN_RESISTANT - 1e-9:
        raise StoreError("skeptics, the satisfied and people without the problem must be at least %d%% of the panel"
                         % (MIN_RESISTANT * 100))
    return shares


def validate_customer(c):
    if not isinstance(c, dict):
        raise StoreError("the lab profile must be a JSON object")
    for k in ("business", "target", "situation", "segments", "alternatives"):
        if c.get(k) in (None, "", []):
            raise StoreError("the lab profile needs '%s'%s" % (k, {
                "situation": ": a neutral description of the moment being studied, with no mention of your product",
                "alternatives": ": what these people use or do today (including 'nothing')"}.get(k, "")))
    if not isinstance(c["segments"], list) or not all(isinstance(s, dict) and s.get("name") for s in c["segments"]):
        raise StoreError("every segment needs a name")
    if sum(float(s.get("share", 1)) for s in c["segments"]) <= 0:
        raise StoreError("the segment shares add up to nothing")
    age = c.get("age")
    if age is not None and not (isinstance(age, list) and len(age) == 2 and all(isinstance(v, int) for v in age) and age[0] <= age[1]):
        raise StoreError("age must be a range like [25, 45]")
    hits = PROMO.findall(c["situation"])
    if hits:
        raise StoreError("the situation text reads like a pitch. Describe the moment neutrally.")


def check_offer(text):
    """Refuse promotional language in what the simulated profiles are shown."""
    found = sorted({m.group(0).lower() for m in PROMO.finditer(text)})
    if found:
        raise StoreError("the offer contains promotional language (%s). Describe what it is, what it does, what it costs"
                         " and how to get it, in plain words." % ", ".join(found))
    if len(text.split()) < 8:
        raise StoreError("the offer is too thin to react to: say what it is, for whom, the price and how to get it")


def deal(customer, n, seed, arms):
    """Deal n profiles. Same profile + n + seed + arms = the same cards, every time."""
    validate_customer(customer)
    if not 10 <= n <= 500:
        raise StoreError("a lab run has 10 to 500 profiles (got %d)" % n)
    rng = random.Random(seed)
    shares = archetype_mix(customer)
    arche = []
    counts = dict(zip(ARCHETYPE_IDS, _quota([shares[a] for a in ARCHETYPE_IDS], n)))
    spare = counts["enthusiast"] - int(n * MAX_ENTHUSIAST)
    if spare > 0:                      # rounding must never push enthusiasts over the cap: the extra seats go to skeptics
        counts["enthusiast"] -= spare
        counts["skeptic"] += spare
    for a in ARCHETYPE_IDS:
        arche += [a] * counts[a]
    segs = []
    for s, k in zip(customer["segments"], _quota([float(s.get("share", 1)) for s in customer["segments"]], n)):
        segs += [s] * k
    rng.shuffle(arche)
    rng.shuffle(segs)
    arm_ids = [a["id"] for a in arms]
    arm_deal = (arm_ids * (n // len(arm_ids) + 1))[:n]
    rng.shuffle(arm_deal)

    def pick(key):
        items = customer.get(key) or []
        return items[rng.randrange(len(items))] if items else ""

    age = customer.get("age")
    cards = []
    for i in range(n):
        s = segs[i]
        card = {"id": "S%03d" % (i + 1), "archetype": arche[i], "arm": arm_deal[i], "segment": s["name"]}
        if age:
            card["age"] = rng.randint(int(age[0]), int(age[1]))
        if s.get("income"):
            card["income"] = int(round(rng.uniform(float(s["income"][0]), float(s["income"][1])), -3))
        for key, field in (("occupations", "occupation"), ("behaviours", "behaviour"), ("habits", "context"),
                           ("purchase_contexts", "purchase_context"), ("experience_levels", "experience")):
            v = pick(key)
            if isinstance(v, dict):
                v = "%s. %s" % (v.get("name", ""), v.get("how", ""))
            if v:
                card[field] = v.strip()
        card["uses_today"] = pick("alternatives")
        if arche[i] == "no_problem":
            card["uses_today"] = card["uses_today"] or "nothing"
        cards.append(card)
    return cards


def card_text(card, target):
    L = ["Profile %s. One of these people: %s." % (card["id"], target), "Group: %s." % card["segment"]]
    if "age" in card:
        L.append("Age %d." % card["age"])
    if "occupation" in card:
        L.append("Work: %s." % card["occupation"])
    if "income" in card:
        L.append("Income about %s a year." % "{:,}".format(card["income"]))
    if "experience" in card:
        L.append("Experience: %s." % card["experience"])
    if "behaviour" in card:
        L.append("How you buy: %s" % card["behaviour"])
    if "context" in card:
        L.append("Your day: %s." % card["context"])
    if "purchase_context" in card:
        L.append("When you would be deciding: %s." % card["purchase_context"])
    L.append("What you use or do today: %s." % card["uses_today"])
    return "\n".join(L)


def init_run(store, customer, arms, n=100, seed=None, model=None, repeats=1, assumptions="", concept_id=None):
    if not (model or "").strip():
        raise StoreError("record which model will answer (--model). If the host does not show it, say so in words;"
                         " a run without it cannot be reproduced or calibrated.")
    if not arms:
        raise StoreError("the lab needs at least one arm: {id, offer, price, scenario}")
    ids = [a.get("id") for a in arms]
    if len(set(ids)) != len(ids) or not all(ids):
        raise StoreError("every arm needs a unique id")
    for a in arms:
        if not a.get("offer") or not a.get("scenario"):
            raise StoreError("arm %s needs 'offer' and 'scenario' (the moment the person meets the offer)" % a["id"])
        check_offer(a["offer"])
    if not 1 <= repeats <= 5:
        raise StoreError("repeats must be 1 to 5")
    if seed is None:
        seed = random.SystemRandom().randrange(1, 10 ** 6)
    cards = deal(customer, n, seed, arms)
    basis = customer.get("evidence_basis") or {}
    method = "Dealt by quota from the founder's customer profile (seed %d). Shares are dealing quotas, not market statistics. Basis: %s." % (
        seed, "; ".join("%s = %s" % (k, v) for k, v in sorted(basis.items())) or "not stated, so treat every field as an assumption")
    stimulus = canonical({"customer": customer, "arms": arms})
    rid = store.insert("syn_runs", {
        "kind": "lab", "model": model.strip(), "prompt_version": PROMPT_VERSION, "persona_method": method,
        "seed": seed, "n_personas": n, "repeats": repeats, "scenario": customer["situation"],
        "assumptions": assumptions or "", "stimulus_sha256": sha256_text(stimulus),
        "arms_json": canonical(arms), "concept_id": concept_id})
    for c in cards:
        store.insert("syn_personas", {"run_id": rid, "persona_id": c["id"], "archetype": c["archetype"],
                                      "arm": c["arm"], "card_json": canonical(c)}, auto_id=False)
    d = run_dir(store, rid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "stimulus.json"), "w", encoding="utf-8") as fh:
        json.dump({"customer": customer, "arms": arms}, fh, indent=1, ensure_ascii=False)
    return rid


def run_dir(store, rid):
    return os.path.join(store.dir, "synth", rid)


def _answer_path(d, stage, pid, repeat):
    return os.path.join(d, "answers", stage, "%s.r%d.json" % (pid, repeat))


def check_answer(a, pid, stage, arm):
    """None if a parsed answer is usable, else a short problem string."""
    if not isinstance(a, dict):
        return "not a JSON object"
    if a.get("id") != pid:
        return "id is %r, expected %s" % (a.get("id"), pid)
    if a.get("stage") != stage:
        return "stage is %r, expected %s" % (a.get("stage"), stage)
    if stage == "problem":
        if a.get("experiences_problem") not in EXPERIENCES:
            return "experiences_problem must be one of %s" % ", ".join(EXPERIENCES)
        if not isinstance(a.get("severity"), int) or not 1 <= a["severity"] <= 5:
            return "severity must be 1 to 5"
    else:
        if a.get("arm") != arm:
            return "arm is %r, expected %s" % (a.get("arm"), arm)
        if a.get("stance") not in STANCES:
            return "stance must be one of %s" % ", ".join(STANCES)
        if a.get("reason_code") not in REASONS:
            return "reason_code must be one of %s" % ", ".join(REASONS)
        if not str(a.get("reason") or "").strip():
            return "no reason given"
    return None


def _file_problem(path, pid, stage, arm):
    if not os.path.exists(path):
        return "missing"
    try:
        with open(path, encoding="utf-8") as fh:
            a = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "not valid JSON"
    return check_answer(a, pid, stage, arm)


def write_briefs(store, rid, stage, wave=10):
    """Write the briefs still to be answered for one stage. Returns waves of (id, repeat, brief path)."""
    if stage not in STAGES:
        raise StoreError("stage must be problem or concept")
    run = store.get("syn_runs", rid, "synthetic run")
    if run["kind"] != "lab":
        raise StoreError("%s was imported, not run in the lab" % rid)
    d = run_dir(store, rid)
    with open(os.path.join(d, "stimulus.json"), encoding="utf-8") as fh:
        stim = json.load(fh)
    customer, arms = stim["customer"], {a["id"]: a for a in stim["arms"]}
    disp = {a[0]: a[2] for a in ARCHETYPES}
    os.makedirs(os.path.join(d, "briefs", stage), exist_ok=True)
    os.makedirs(os.path.join(d, "answers", stage), exist_ok=True)
    todo = []
    for p in store.rows("SELECT * FROM syn_personas WHERE run_id = ? ORDER BY persona_id", (rid,)):
        card = json.loads(p["card_json"])
        for rep in range(1, run["repeats"] + 1):
            out = _answer_path(d, stage, card["id"], rep)
            if _file_problem(out, card["id"], stage, card["arm"]) is None:
                continue
            common = dict(card=card_text(card, customer["target"]), disposition=disp[card["archetype"]],
                          name="profile " + card["id"], id=card["id"], out=os.path.abspath(out))
            if stage == "problem":
                brief = PROBLEM_BRIEF.format(situation=customer["situation"], experiences=" / ".join(EXPERIENCES), **common)
            else:
                arm = arms[card["arm"]]
                price = arm.get("price")
                brief = CONCEPT_BRIEF.format(
                    offer=arm["offer"].strip(), scenario=arm["scenario"].strip(), arm=arm["id"],
                    price_line=("Price: %s" % price) if price not in (None, "") else "No price is shown.",
                    alternatives="\n".join("- %s" % a for a in customer["alternatives"]),
                    stances=" / ".join(STANCES), reasons=" / ".join(REASONS), **common)
            bp = os.path.join(d, "briefs", stage, "%s.r%d.md" % (card["id"], rep))
            with open(bp, "w", encoding="utf-8") as fh:
                fh.write(brief)
            todo.append((card["id"], rep, os.path.abspath(bp)))
    return [todo[i:i + wave] for i in range(0, len(todo), wave)]


def ingest(store, rid):
    """File the sub-agents' answer files into the synthetic tables. Returns (filed, problems)."""
    run = store.get("syn_runs", rid, "synthetic run")
    d = run_dir(store, rid)
    filed, problems = 0, []
    have = {(r["persona_id"], r["stage"], r["repeat"]) for r in store.rows(
        "SELECT persona_id, stage, repeat FROM syn_responses WHERE run_id = ?", (rid,))}
    for p in store.rows("SELECT * FROM syn_personas WHERE run_id = ? ORDER BY persona_id", (rid,)):
        for stage in STAGES:
            for rep in range(1, run["repeats"] + 1):
                if (p["persona_id"], stage, rep) in have:
                    continue
                path = _answer_path(d, stage, p["persona_id"], rep)
                if not os.path.exists(path):
                    continue
                prob = _file_problem(path, p["persona_id"], stage, p["arm"])
                if prob:
                    problems.append((p["persona_id"], stage, rep, prob))
                    continue
                with open(path, encoding="utf-8") as fh:
                    answer = json.load(fh)
                store.insert("syn_responses", {"run_id": rid, "persona_id": p["persona_id"], "stage": stage,
                                               "repeat": rep, "answer_json": canonical(answer)})
                filed += 1
    return filed, problems


def import_panel(store, panel_dir, model="not recorded"):
    """Bring a founder-consumer panel into the synthetic tables, so it is on the record as simulated."""
    try:
        with open(os.path.join(panel_dir, "panel.json"), encoding="utf-8") as fh:
            state = json.load(fh)
        with open(os.path.join(panel_dir, "personas.json"), encoding="utf-8") as fh:
            cards = json.load(fh)
    except FileNotFoundError:
        raise StoreError("no founder-consumer panel in %s" % panel_dir)
    stimulus = canonical({"customer": state["customer"], "pitch": state["pitch"]})
    digest = sha256_text(stimulus + str(state["seed"]))
    if store.one("SELECT id FROM syn_runs WHERE stimulus_sha256 = ?", (digest,)):
        raise StoreError("this panel was already imported")
    rid = store.insert("syn_runs", {
        "kind": "imported_panel", "model": model, "prompt_version": "founder-consumer panel.py",
        "persona_method": "Dealt by founder-consumer from the founder's customer profile (seed %s). No forced skeptics."
                          % state["seed"],
        "seed": state["seed"], "n_personas": len(cards), "repeats": 1, "scenario": state["pitch"],
        "assumptions": "single-stage buy/pass panel; the offer was shown with the problem", "stimulus_sha256": digest,
        "arms_json": "[]"})
    filed = 0
    for c in cards:
        store.insert("syn_personas", {"run_id": rid, "persona_id": c["id"], "archetype": c.get("behaviour", "panel"),
                                      "arm": None, "card_json": canonical(c)}, auto_id=False)
        path = os.path.join(panel_dir, "answers", c["id"] + ".json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    a = json.load(fh)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(a, dict):
                continue
            store.insert("syn_responses", {"run_id": rid, "persona_id": c["id"], "stage": "panel", "repeat": 1,
                                           "answer_json": canonical(a)})
            filed += 1
    return rid, filed


def _norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", "", str(s).lower()).split())


def _unique(texts, limit=15):
    seen, out = set(), []
    for t in texts:
        t = " ".join(str(t or "").split())
        if not t or _norm(t) in seen:
            continue
        seen.add(_norm(t))
        out.append(t)
    return out[:limit]


def tally(store, rid):
    """Summarise a run as research material: themes, objections, questions. No conversion rate."""
    run = store.get("syn_runs", rid, "synthetic run")
    personas = {p["persona_id"]: p for p in store.rows("SELECT * FROM syn_personas WHERE run_id = ?", (rid,))}
    rows = store.rows("SELECT * FROM syn_responses WHERE run_id = ? ORDER BY persona_id, stage, repeat", (rid,))
    if not rows:
        raise StoreError("no answers filed for %s yet: run the briefs, then 'synth ingest'" % rid)
    by_stage = {}
    for r in rows:
        a = json.loads(r["answer_json"])
        a["_persona"], a["_repeat"], a["_archetype"] = r["persona_id"], r["repeat"], personas[r["persona_id"]]["archetype"]
        a["_arm"] = personas[r["persona_id"]]["arm"]
        by_stage.setdefault(r["stage"], []).append(a)
    res = {"run": rid, "kind": run["kind"], "model": run["model"], "prompt_version": run["prompt_version"],
           "seed": run["seed"], "profiles": run["n_personas"], "repeats": run["repeats"],
           "persona_method": run["persona_method"], "assumptions": run["assumptions"],
           "independent_market_observations": 0,
           "warning": "SIMULATED. %d profiles answered by one model (%s) are %d correlated outputs of that model, not %d"
                      " independent people. Use for questions and objections only." % (
                          run["n_personas"], run["model"], run["n_personas"], run["n_personas"])}
    first = lambda items: [a for a in items if a["_repeat"] == 1]

    def table(items, field, values):
        out = {}
        for a in items:
            row = out.setdefault(a["_archetype"], {v: 0 for v in values})
            if a.get(field) in row:
                row[a[field]] += 1
        return out

    def wobble(items, field):
        seen = {}
        for a in items:
            seen.setdefault(a["_persona"], set()).add(a.get(field))
        multi = [v for p, v in seen.items() if sum(1 for a in items if a["_persona"] == p) > 1]
        if not multi:
            return None
        return {"profiles_repeated": len(multi), "changed_answer": sum(1 for v in multi if len(v) > 1)}

    questions = []
    if "problem" in by_stage:
        items = first(by_stage["problem"])
        res["problem"] = {
            "answered": len(items), "by_archetype": table(items, "experiences_problem", EXPERIENCES),
            "current_solutions": _unique(a.get("current_solution") for a in items),
            "costs": _unique(a.get("cost_of_problem") for a in items if a.get("experiences_problem") in ("often", "sometimes")),
            "do_nothing": _unique(a.get("if_nothing_changes") for a in items),
            "wobble": wobble(by_stage["problem"], "experiences_problem")}
        for a in items:
            questions += a.get("questions_for_real_people") or []
    if "concept" in by_stage:
        res["concept"] = {}
        for arm in sorted({a["_arm"] for a in by_stage["concept"]}):
            items = [a for a in first(by_stage["concept"]) if a["_arm"] == arm]
            reasons = {}
            for a in items:
                if a["stance"] in ("indifferent", "skeptical", "rejects"):
                    reasons.setdefault(a["reason_code"], []).append(a)
            mix = {s: sum(1 for a in items if a["stance"] == s) for s in STANCES}
            res["concept"][arm] = {
                "answered": len(items), "by_archetype": table(items, "stance", STANCES), "stance_mix": mix,
                "reasons_to_reject": [{"code": k, "profiles": len(v), "examples": _unique((a["reason"] for a in v), 3)}
                                      for k, v in sorted(reasons.items(), key=lambda kv: -len(kv[1]))],
                "objections": _unique(a.get("main_objection") for a in items),
                "adoption_barriers": _unique(a.get("adoption_barrier") for a in items),
                "purchase_triggers": _unique(a.get("purchase_trigger") for a in items),
                "alternative_uses": _unique(a.get("other_use") for a in items),
                "alternatives_preferred": _unique(a.get("alternative_i_would_use") for a in items),
                "who_decides": _unique((a.get("who_decides") for a in items), 8),
                "who_pays": _unique((a.get("who_pays") for a in items), 8),
                "price_answers": sum(1 for a in items if all(isinstance(a.get("price_" + k), (int, float)) for k in
                                                             ("too_cheap", "cheap", "expensive", "too_expensive"))),
                "wobble": wobble([a for a in by_stage["concept"] if a["_arm"] == arm], "stance"),
                "calibration_only": {
                    "measure": "share of simulated profiles whose stance is would_seek_out or interested",
                    "value": (mix["would_seek_out"] + mix["interested"]) / float(len(items)) if items else None,
                    "note": "Set largely by the disposition quotas dealt into the panel. Kept only so it can be compared"
                            " with a real result later. It is not a conversion rate."}}
            for a in items:
                questions += a.get("questions_for_real_people") or []
    if "panel" in by_stage:
        items = by_stage["panel"]
        reasons = {}
        for a in items:
            if a.get("buys") is False:
                reasons.setdefault(a.get("reason_code", "other"), []).append(a)
        res["panel"] = {"answered": len(items),
                        "said_buy": sum(1 for a in items if a.get("buys") is True),
                        "said_pass": sum(1 for a in items if a.get("buys") is False),
                        "reasons_to_reject": [{"code": k, "profiles": len(v), "examples": _unique((a.get("reason") for a in v), 3)}
                                              for k, v in sorted(reasons.items(), key=lambda kv: -len(kv[1]))],
                        "objections": _unique(a.get("objection") for a in items),
                        "note": "Imported founder-consumer panel. No forced skeptics, so it leans agreeable."}
    res["questions_for_real_customers"] = _unique(questions, 25)
    res["hypotheses_to_test"] = _suggest(res)
    return res


SUGGEST = {
    "price": "Real buyers in the target segment reject the offer at this price. Test with a real offer at two prices.",
    "habit": "The current habit is strong enough that buyers will not switch. Ask real people what last made them switch.",
    "no_need": "A large share of the target segment does not have the problem. Screen for the problem before anything else.",
    "trust": "Buyers do not believe the offer will deliver. Find out what proof real buyers asked for last time.",
    "quality": "Buyers doubt the quality is high enough. Test with a sample, a demo or a concierge delivery.",
    "effort": "Setup or switching effort blocks adoption. Watch a real person go through the first use.",
    "timing": "Buyers only act at a specific trigger moment. Find the trigger in interviews and reach people at it.",
    "not_my_decision": "The user is not the buyer. Map who holds the budget and interview that person.",
    "fit": "The offer does not fit how the segment works. Check the workflow in interviews before changing the product.",
}


def _suggest(res):
    out, seen = [], set()
    blocks = list((res.get("concept") or {}).values()) + ([res["panel"]] if res.get("panel") else [])
    for block in blocks:
        for r in block["reasons_to_reject"][:4]:
            if r["code"] in SUGGEST and r["code"] not in seen:
                seen.add(r["code"])
                out.append({"from_reason": r["code"], "hypothesis": SUGGEST[r["code"]], "category": "A"})
    return out


def results_md(res):
    L = ["# Synthetic customer lab: run %s" % res["run"], "",
         "> **SIMULATED. Not customers.** %s" % res["warning"], "",
         "| | |", "| --- | --- |",
         "| Model | %s |" % res["model"], "| Prompt version | %s |" % res["prompt_version"],
         "| Seed | %s |" % res["seed"], "| Profiles | %d, each answered %d time(s) |" % (res["profiles"], res["repeats"]),
         "| How profiles were made | %s |" % res["persona_method"],
         "| Assumptions | %s |" % (res["assumptions"] or "none recorded"),
         "| Independent observations of the market | 0 |", ""]

    def grid(title, table, values):
        L.extend(["### %s" % title, "", "| disposition | " + " | ".join(values) + " |",
                  "| --- |" + " ---: |" * len(values)])
        for arche in ARCHETYPE_IDS:
            if arche in table:
                L.append("| %s | %s |" % (arche, " | ".join(str(table[arche][v]) for v in values)))
        for arche in sorted(set(table) - set(ARCHETYPE_IDS)):
            L.append("| %s | %s |" % (arche, " | ".join(str(table[arche][v]) for v in values)))
        L.append("")

    def bullets(title, items):
        if items:
            L.extend(["### %s" % title, ""] + ["- (simulated) %s" % i for i in items] + [""])

    def wobble(w):
        if w:
            L.extend(["Repeat sensitivity: %d of %d repeated profiles changed their answer between runs." % (
                w["changed_answer"], w["profiles_repeated"]), ""])

    if res.get("problem"):
        p = res["problem"]
        L += ["## Stage 1: the problem, with no solution shown (%d simulated answers)" % p["answered"], ""]
        grid("Simulated: how often the situation is a problem, by disposition", p["by_archetype"], EXPERIENCES)
        L += ["The counts follow the dispositions you dealt. They say nothing about how common the problem is.", ""]
        wobble(p["wobble"])
        bullets("What simulated profiles said they do today", p["current_solutions"])
        bullets("What they said it costs them", p["costs"])
    for arm, c in sorted((res.get("concept") or {}).items()):
        L += ["## Stage 2: the offer, arm %s (%d simulated answers)" % (arm, c["answered"]), ""]
        grid("Simulated stance by disposition", c["by_archetype"], STANCES)
        L += ["This mix is set largely by the disposition quotas. It is not a buy rate and must not be read as one.", ""]
        wobble(c["wobble"])
        if c["reasons_to_reject"]:
            L += ["### Reasons to reject", "", "| reason | simulated profiles | examples (simulated, not quotes from customers) |",
                  "| --- | ---: | --- |"]
            for r in c["reasons_to_reject"]:
                L.append("| %s | %d | %s |" % (r["code"], r["profiles"], " / ".join(e.replace("|", "/") for e in r["examples"])))
            L.append("")
        bullets("Possible objections", c["objections"])
        bullets("Adoption barriers", c["adoption_barriers"])
        bullets("Possible purchase triggers", c["purchase_triggers"])
        bullets("Alternative uses and users", c["alternative_uses"])
        bullets("Who decides", c["who_decides"])
        bullets("Who pays", c["who_pays"])
    if res.get("panel"):
        p = res["panel"]
        L += ["## Imported founder-consumer panel (%d simulated answers)" % p["answered"], "",
              "%d simulated profiles said buy, %d said pass. %s" % (p["said_buy"], p["said_pass"], p["note"]), ""]
        bullets("Possible objections", p["objections"])
    L += ["## Questions to take to real customers", ""]
    L += ["- %s" % q for q in res["questions_for_real_customers"]] or ["- none produced"]
    L += ["", "## Hypotheses this run suggests (category A: untested)", ""]
    L += ["- %s (from reason: %s)" % (h["hypothesis"], h["from_reason"]) for h in res["hypotheses_to_test"]] or ["- none"]
    L += ["", "_Nothing in this file is evidence of demand. It decides what to ask and test next._"]
    return "\n".join(L) + "\n"


def price_rows(store, rid):
    """Four-price answers from a synthetic run, for exploratory Van Westendorp only."""
    out = []
    for r in store.rows("SELECT answer_json FROM syn_responses WHERE run_id = ? AND repeat = 1", (rid,)):
        a = json.loads(r["answer_json"])
        row = tuple(a.get("price_" + k) for k in ("too_cheap", "cheap", "expensive", "too_expensive"))
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in row) and row[0] <= row[1] <= row[2] <= row[3]:
            out.append(row)
    return out
