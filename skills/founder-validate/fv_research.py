"""Real customer research for founder-validate. Standard library only, no network.

Participants, consent, interviews, extracts, surveys and their analysis. The
tool records what real people said. It cannot recruit anyone, interview anyone
or fill in a survey: every row here is something the founder imported, and the
tool refuses the shortcuts that would let an AI summary pass as a customer's
words:

  - an interview needs a participant whose consent is on record;
  - a verbatim quote must appear, word for word, in the stored transcript;
  - interviewer notes can only produce summaries, never quotes;
  - a survey response is never deleted, only excluded with a stated reason.
"""

import csv
import json
import os
import re
import shutil

import fv_stats as stats
from fv_store import (StoreError, PAST_BEHAVIOUR_KINDS, QUESTION_KINDS, canonical, check_date, now, sha256_file,
                      sha256_text, today)

# ── question linting ────────────────────────────────────────────────────────────
LINT_RULES = [
    ("hypothetical", r"\b(would|will) you\b|\bwould (it|that|this)\b|\bif (we|there|you could|i)\b|\bimagine\b|\bsuppose\b",
     "Hypothetical. People guess about their future selves. Ask about the last time it actually happened."),
    ("leading", r"\bdon'?t you\b|\bwouldn'?t (it|you)\b|\bisn'?t it\b|\bdo you agree\b|\bhow (much )?(do|did) you (love|like)\b"
                r"|\bhow (useful|great|helpful|valuable|frustrating|annoying|painful)\b",
     "Leading. The wording assumes the answer. Ask a neutral, open question."),
    ("stated_wtp", r"\b(would|will) you (pay|buy)\b|\bhow much would you\b|\bwilling to pay\b",
     "Stated willingness to pay. Ask what they paid the last time, to whom. If you still ask this, the answer is a"
     " stated preference, not demand."),
    ("pitch", r"\bour (app|product|solution|tool|platform|service|idea)\b|\bmy (app|product|idea|startup)\b",
     "Mentions your solution. In a problem interview the solution stays out of the room."),
    ("double", r"\?.+\?|\b(how|what|when|why|do|did)\b[^?]*\band\b\s+(how|what|when|why|do|did)\b",
     "Two questions in one. Split it so you know which one was answered."),
]
PAST = re.compile(r"\b(last time|have you ever|did you|what did|when did|how did|how often|tell me about|walk me through"
                  r"|in the (last|past)|how many times|what happened|was|were|paid|bought|tried|signed|raised|took|went|used"
                  r"|spent|stopped|recommended)\b", re.I)


def lint_question(text, context="interview", kind=None):
    """Return a list of (rule, message) problems with one question. Empty list = no flags."""
    t = " ".join(str(text).split())
    out = []
    for rule, pattern, message in LINT_RULES:
        if not re.search(pattern, t, re.I):
            continue
        if context == "survey" and kind in ("stated", "pricing") and rule in ("hypothetical", "stated_wtp"):
            continue  # a stated-preference question is allowed to be one: it is labelled and capped as such
        if context == "solution" and rule == "pitch":
            continue
        if context != "survey" and rule == "double":
            continue  # a spoken follow-up ("What happened?") is fine; a survey item gets one answer, so it is not
        out.append((rule, message))
    return out


def lint_guide(text, guide_type="problem_discovery"):
    """Lint every question line of a markdown guide. Returns {'questions': n, 'flags': [...], 'past_share': x}."""
    context = "interview" if guide_type in ("problem_discovery", "purchasing") else "solution"
    questions, flags, past = [], [], 0
    items = []          # (first line number, text), with wrapped continuation lines joined
    for i, line in enumerate(text.splitlines(), 1):
        if items and line[:1] in (" ", "\t") and line.strip() and items[-1][1]:
            items[-1] = (items[-1][0], items[-1][1] + " " + line.strip())
        else:
            items.append((i, line.strip()))
    for i, s in items:
        if "?" not in s or s.startswith("#") or s.startswith(">"):
            continue
        q = re.sub(r"^([-*]|\d+[.)])\s*", "", s)
        questions.append(q)
        if PAST.search(q):
            past += 1
        for rule, message in lint_question(q, context):
            flags.append({"line": i, "question": q, "rule": rule, "message": message})
    return {"questions": len(questions), "flags": flags,
            "past_share": (past / float(len(questions))) if questions else None}


# ── participants ────────────────────────────────────────────────────────────────
def add_participant(store, p):
    if p.get("segment_id"):
        store.get("segments", p["segment_id"], "segment")
    consent = p.get("consent", "none")
    if consent == "recorded" and not p.get("consent_scope"):
        raise StoreError("recorded consent needs consent_scope: what the person agreed to (recording, quotes, storage)")
    return store.insert("participants", {
        "label": p.get("label", ""), "segment_id": p.get("segment_id"), "role": p.get("role", "unknown"),
        "recruited_via": p.get("recruited_via", ""), "status": p.get("status", "invited"),
        "consent": consent, "consent_on": check_date(p["consent_on"], "consent_on") if p.get("consent_on") else (
            today() if consent == "recorded" else None),
        "consent_scope": p.get("consent_scope", ""), "characteristics": p.get("characteristics", "")})


def update_participant(store, pid, changes):
    store.get("participants", pid, "participant")
    allowed = {"status", "segment_id", "role", "consent", "consent_on", "consent_scope", "characteristics",
               "recruited_via", "label"}
    bad = set(changes) - allowed
    if bad:
        raise StoreError("cannot change %s on a participant" % ", ".join(sorted(bad)))
    if changes.get("consent") == "recorded":
        if not changes.get("consent_scope"):
            raise StoreError("recorded consent needs consent_scope")
        changes.setdefault("consent_on", today())
    store.update("participants", pid, changes)


def redact_participant(store, pid, reason):
    """Honour a withdrawal: remove what the person said, keep the fact that a record existed."""
    if not (reason or "").strip():
        raise StoreError("a redaction needs a reason (for example: participant withdrew consent)")
    store.get("participants", pid, "participant")
    stamp = now()
    for iv in store.rows("SELECT * FROM interviews WHERE participant_id = ?", (pid,)):
        if iv["record_path"] and os.path.exists(iv["record_path"]):
            os.remove(iv["record_path"])
        store.update("interviews", iv["id"], {"record_path": None}, action="redact")
        for x in store.rows("SELECT id FROM interview_extracts WHERE interview_id = ?", (iv["id"],)):
            store.db.execute("UPDATE interview_extracts SET redacted_at = ?, text = '[removed at the participant''s request]',"
                             " amount = NULL WHERE id = ?", (stamp, x["id"]))
            store.audit("redact", "interview_extracts", x["id"], {"reason": reason})
    store.update("participants", pid, {"label": "", "characteristics": "", "status": "withdrawn", "consent": "none",
                                       "redacted_at": stamp}, action="redact")


def recruitment(store):
    """Where recruitment actually stands, counted from participant rows. Nothing is projected."""
    targets = json.loads(store.meta("recruit_targets", "{}"))
    segs = {s["id"]: s["name"] for s in store.rows("SELECT id, name FROM segments")}
    out = []
    keys = list(segs) + [None]
    for sid in keys:
        rows = store.rows("SELECT status, COUNT(*) AS n FROM participants WHERE segment_id IS ? AND redacted_at IS NULL"
                          " GROUP BY status", (sid,))
        counts = {r["status"]: r["n"] for r in rows}
        if not counts and sid not in targets and str(sid) not in targets:
            continue
        out.append({"segment_id": sid, "segment": segs.get(sid, "(no segment)"), "target": targets.get(sid or ""),
                    "counts": counts, "interviewed": counts.get("interviewed", 0)})
    return out


# ── interviews ──────────────────────────────────────────────────────────────────
_TIMING = re.compile(r"^\s*(\d+\s*$|WEBVTT|\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s*-->)")


def normalise(text):
    """Lower-case, straight quotes, single spaces. Used only to check a quote against its transcript."""
    t = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    t = t.replace("…", "...")
    return " ".join(t.lower().split())


def transcript_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    if path.lower().endswith((".vtt", ".srt")):
        lines = [l for l in lines if not _TIMING.match(l)]
    return "\n".join(lines)


def add_interview(store, iv):
    for k in ("participant_id", "guide_type", "conducted_on", "record_kind", "record_path"):
        if not iv.get(k):
            raise StoreError("interview needs '%s'" % k)
    p = store.get("participants", iv["participant_id"], "participant")
    if p["redacted_at"]:
        raise StoreError("%s withdrew: no new records for this participant" % p["id"])
    if p["consent"] != "recorded":
        raise StoreError("%s has no consent on record. Record what they agreed to first (participant update), or do not"
                         " store the interview." % p["id"])
    src = iv["record_path"]
    if not os.path.isfile(src):
        raise StoreError("no such file: %s (the tool does not transcribe audio: import a transcript or your notes)" % src)
    if src.lower().endswith((".mp3", ".m4a", ".wav", ".mp4", ".mov", ".ogg", ".webm")):
        raise StoreError("%s is a recording. Transcribe it first (any tool you trust), then import the text." % src)
    iid = store.next_id("interviews")
    dest_dir = os.path.join(store.dir, "records")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, iid + os.path.splitext(src)[1].lower())
    shutil.copyfile(src, dest)
    store.insert("interviews", {
        "participant_id": p["id"], "guide_type": iv["guide_type"],
        "conducted_on": check_date(iv["conducted_on"], "conducted_on"), "interviewer": iv.get("interviewer", ""),
        "medium": iv.get("medium", ""), "record_kind": iv["record_kind"], "record_path": dest,
        "record_sha256": sha256_file(dest), "concept_id": iv.get("concept_id")})
    if p["status"] != "interviewed":
        store.update("participants", p["id"], {"status": "interviewed"})
    return iid


def add_extract(store, x):
    """One thing taken from one interview. verbatim=true is checked against the transcript, word for word."""
    for k in ("interview_id", "kind", "text"):
        if not x.get(k):
            raise StoreError("extract needs '%s'" % k)
    iv = store.get("interviews", x["interview_id"], "interview")
    verbatim = bool(x.get("verbatim"))
    text = " ".join(str(x["text"]).split())
    if verbatim:
        if iv["record_kind"] != "transcript":
            raise StoreError("%s is stored as interviewer notes, so nothing in it is a verbatim customer quote."
                             " Save this as a summary (verbatim: false)." % iv["id"])
        if not iv["record_path"] or not os.path.exists(iv["record_path"]):
            raise StoreError("the transcript for %s is gone, so the quote cannot be verified" % iv["id"])
        if sha256_file(iv["record_path"]) != iv["record_sha256"]:
            raise StoreError("the stored transcript for %s has changed since import: quotes cannot be verified against it"
                             % iv["id"])
        quote = text.strip('"').strip()
        if len(quote.split()) < 3:
            raise StoreError("a verbatim quote needs at least three words")
        if normalise(quote) not in normalise(transcript_text(iv["record_path"])):
            raise StoreError("not found in the transcript of %s: %r. Quote the customer exactly, or save it as a summary"
                             " (verbatim: false)." % (iv["id"], quote[:80]))
        text = quote
    amount = x.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise StoreError("amount must be a number")
    return store.insert("interview_extracts", {
        "interview_id": iv["id"], "kind": x["kind"], "text": text, "verbatim": 1 if verbatim else 0,
        "author": x.get("author", "ai"), "theme": (x.get("theme") or "").strip().lower(),
        "amount": amount, "currency": x.get("currency")})


def analyse_interviews(store, segment_id=None):
    """Count themes by distinct participant. Returns a dict; says who was interviewed before any pattern."""
    where, args = "", []
    if segment_id:
        where, args = " AND p.segment_id = ?", [segment_id]
    ivs = store.rows("SELECT i.*, p.segment_id, p.role FROM interviews i JOIN participants p ON p.id = i.participant_id"
                     " WHERE p.redacted_at IS NULL" + where, args)
    segs = {s["id"]: s["name"] for s in store.rows("SELECT id, name FROM segments")}
    people = {}
    for iv in ivs:
        people[iv["participant_id"]] = iv
    by_segment, by_role, by_guide = {}, {}, {}
    for p in people.values():
        name = segs.get(p["segment_id"], "(no segment)")
        by_segment[name] = by_segment.get(name, 0) + 1
        by_role[p["role"]] = by_role.get(p["role"], 0) + 1
    for iv in ivs:
        by_guide[iv["guide_type"]] = by_guide.get(iv["guide_type"], 0) + 1
    themes = {}
    extracts = store.rows(
        "SELECT x.*, i.participant_id, p.segment_id FROM interview_extracts x JOIN interviews i ON i.id = x.interview_id"
        " JOIN participants p ON p.id = i.participant_id WHERE x.redacted_at IS NULL AND p.redacted_at IS NULL" + where, args)
    for x in extracts:
        t = themes.setdefault(x["theme"] or "(untagged)", {"participants": set(), "past_behaviour": set(), "kinds": {},
                                                           "quotes": [], "summaries": []})
        t["participants"].add(x["participant_id"])
        if x["kind"] in PAST_BEHAVIOUR_KINDS:
            t["past_behaviour"].add(x["participant_id"])
        t["kinds"][x["kind"]] = t["kinds"].get(x["kind"], 0) + 1
        (t["quotes"] if x["verbatim"] else t["summaries"]).append({"id": x["id"], "text": x["text"], "kind": x["kind"],
                                                                   "participant": x["participant_id"],
                                                                   "author": x["author"]})
    n = len(people)
    rows = []
    for name, t in themes.items():
        rows.append({"theme": name, "participants": len(t["participants"]), "of": n,
                     "with_past_behaviour": len(t["past_behaviour"]), "kinds": t["kinds"],
                     "quotes": t["quotes"], "summaries": t["summaries"], "outlier": len(t["participants"]) == 1 and n > 1})
    rows.sort(key=lambda r: (-r["participants"], r["theme"]))
    spend = [x for x in extracts if x["kind"] == "spend" and x["amount"] is not None]
    return {"interviews": len(ivs), "participants": n, "by_segment": by_segment, "by_role": by_role, "by_guide": by_guide,
            "themes": rows, "contradictions": [x for x in extracts if x["kind"] == "contradiction"],
            "spend": [{"id": x["id"], "participant": x["participant_id"], "amount": x["amount"], "currency": x["currency"],
                       "text": x["text"], "verbatim": x["verbatim"]} for x in spend],
            "generalise": "%d people. This describes these %d people, not the market." % (n, n) if n else "No interviews yet."}


# ── surveys ─────────────────────────────────────────────────────────────────────
META_COLUMNS = ("respondent_key", "submitted_at", "duration_s")


def validate_instrument(inst):
    """Check a survey instrument. Returns (errors, warnings). Errors block creation."""
    errors, warnings = [], []
    for k in ("title", "population", "questions"):
        if not inst.get(k):
            errors.append("the survey needs '%s'" % k)
    if errors:
        return errors, warnings
    seen = set()
    kinds = set()
    for q in inst["questions"]:
        qid = q.get("id")
        if not qid or qid in seen or qid in META_COLUMNS:
            errors.append("every question needs a unique id (problem at %r)" % qid)
            continue
        seen.add(qid)
        if q.get("kind") not in QUESTION_KINDS:
            errors.append("%s: kind must be one of %s" % (qid, ", ".join(QUESTION_KINDS)))
        kinds.add(q.get("kind"))
        if q.get("type") not in ("single", "multi", "number", "text"):
            errors.append("%s: type must be single, multi, number or text" % qid)
        if q.get("type") in ("single", "multi") and len(q.get("options") or []) < 2:
            errors.append("%s: a choice question needs at least two options" % qid)
        if q.get("kind") == "screening" and not q.get("qualifies"):
            errors.append("%s: a screening question needs 'qualifies': the answers that let someone through" % qid)
        if q.get("qualifies") and not set(q["qualifies"]) <= set(q.get("options") or []):
            errors.append("%s: 'qualifies' lists answers that are not among the options" % qid)
        if q.get("randomize") and q.get("ordered"):
            errors.append("%s: an ordered scale cannot have its options shuffled" % qid)
        if q.get("type") in ("single", "multi") and not q.get("ordered") and not q.get("randomize") \
                and len(q.get("options") or []) > 2:
            warnings.append("%s: unordered options are shown in a fixed order; set randomize to true so the first"
                            " option is not favoured" % qid)
        for rule, message in lint_question(q.get("text", ""), "survey", q.get("kind")):
            (errors if rule == "leading" else warnings).append("%s (%s): %s" % (qid, rule, message))
        if q.get("kind") == "behavioral" and re.search(r"\b(would|will) you\b", q.get("text", ""), re.I):
            errors.append("%s: marked behavioral but asks about the future. Reword to past behaviour or mark it 'stated'." % qid)
    if "screening" not in kinds:
        warnings.append("no screening question: you will not know whether respondents are in your target segment")
    if "behavioral" not in kinds:
        warnings.append("no question about past behaviour: every answer will be a stated preference, which caps what"
                        " this survey can support")
    for name, spec in (("van_westendorp", inst.get("van_westendorp")), ("gabor_granger", inst.get("gabor_granger"))):
        if spec:
            for qid in (spec.values() if isinstance(spec, dict) else []):
                if qid not in seen:
                    errors.append("%s points at an unknown question %r" % (name, qid))
    return errors, warnings


def create_survey(store, inst, meta=None):
    meta = meta or {}
    errors, warnings = validate_instrument(inst)
    if errors:
        raise StoreError("the survey has problems:\n  - " + "\n  - ".join(errors))
    sid = store.insert("surveys", {
        "title": inst["title"], "instrument_json": canonical(inst), "population": inst["population"],
        "distributed_via": meta.get("distributed_via", ""), "concept_id": meta.get("concept_id"),
        "segment_id": meta.get("segment_id")})
    return sid, warnings


def survey_form(inst):
    """A plain form to paste into whatever survey tool you use, plus the CSV header the import expects."""
    L = ["# %s" % inst["title"], "", "Who this is for: %s" % inst["population"], ""]
    if inst.get("intro"):
        L += [inst["intro"], ""]
    for n, q in enumerate(inst["questions"], 1):
        L.append("**%d. %s**%s" % (n, q["text"], "" if q.get("required", True) else " (optional)"))
        note = {"single": "choose one", "multi": "choose all that apply", "number": "a number", "text": "free text"}[q["type"]]
        if q.get("randomize"):
            note += "; shuffle the option order per respondent in your survey tool"
        L.append("_%s. Column id: `%s` (%s)_" % (note, q["id"], q["kind"]))
        for o in q.get("options") or []:
            L.append("- %s" % o)
        L.append("")
    header = ",".join(list(META_COLUMNS) + [q["id"] for q in inst["questions"]])
    L += ["---", "", "Export the answers as CSV with these column names (multi-choice answers separated by `;`):", "",
          "```", header, "```", ""]
    return "\n".join(L), header


def _parse_answer(q, raw):
    raw = (raw or "").strip()
    if raw == "":
        return None
    if q["type"] == "number":
        try:
            return float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            return None
    if q["type"] == "multi":
        return [a.strip() for a in raw.split(";") if a.strip()]
    return raw


def import_responses(store, survey_id, csv_path, fielded_from=None, fielded_to=None, distributed_via=None):
    """Load a CSV export. Applies the instrument's exclusion rules in a fixed order and keeps every row."""
    sv = store.get("surveys", survey_id, "survey")
    inst = json.loads(sv["instrument_json"])
    if not os.path.isfile(csv_path):
        raise StoreError("no such file: %s" % csv_path)
    batch = "%s:%s" % (os.path.basename(csv_path), sha256_file(csv_path)[:12])
    if store.one("SELECT 1 AS x FROM survey_responses WHERE survey_id = ? AND import_batch = ?", (survey_id, batch)):
        raise StoreError("this exact file was already imported into %s" % survey_id)
    seen_keys = {r["respondent_key"] for r in store.rows(
        "SELECT respondent_key FROM survey_responses WHERE survey_id = ? AND respondent_key IS NOT NULL", (survey_id,))}
    seen_rows = {r["row_sha256"] for r in store.rows("SELECT row_sha256 FROM survey_responses WHERE survey_id = ?", (survey_id,))}
    report = {"read": 0, "valid": 0, "excluded": {}, "warnings": []}
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = set(reader.fieldnames or [])
        missing = [q["id"] for q in inst["questions"] if q["id"] not in cols]
        if missing:
            raise StoreError("the CSV has no column for: %s" % ", ".join(missing))
        has_key = "respondent_key" in cols
        has_stamp = "submitted_at" in cols
        for raw in reader:
            report["read"] += 1
            answers = {q["id"]: _parse_answer(q, raw.get(q["id"])) for q in inst["questions"]}
            key = (raw.get("respondent_key") or "").strip() or None
            stamp = (raw.get("submitted_at") or "").strip() or None
            try:
                duration = float(raw["duration_s"]) if (raw.get("duration_s") or "").strip() else None
            except ValueError:
                duration = None
            row_hash = sha256_text(canonical({"a": answers, "k": key, "t": stamp, "d": duration}))
            reason = None
            if key and key in seen_keys:
                reason = "duplicate_respondent"
            elif (key or stamp) and row_hash in seen_rows:
                reason = "duplicate_row"
            elif any(answers[q["id"]] in (None, []) for q in inst["questions"] if q.get("required", True)):
                reason = "incomplete"
            else:
                for q in inst["questions"]:
                    if q["kind"] == "screening":
                        a = answers[q["id"]]
                        got = set(a) if isinstance(a, list) else {a}
                        if not got & set(q["qualifies"]):
                            reason = "screened_out"
                            break
                if reason is None and inst.get("min_duration_s") and duration is not None \
                        and duration < float(inst["min_duration_s"]):
                    reason = "too_fast"
            if key:
                seen_keys.add(key)
            seen_rows.add(row_hash)
            store.insert("survey_responses", {
                "survey_id": survey_id, "respondent_key": key, "submitted_at": stamp, "duration_s": duration,
                "answers_json": canonical(answers), "row_sha256": row_hash, "excluded_reason": reason,
                "import_batch": batch})
            if reason:
                report["excluded"][reason] = report["excluded"].get(reason, 0) + 1
            else:
                report["valid"] += 1
    if not has_key:
        report["warnings"].append("no respondent_key column: the same person answering twice cannot be detected")
    if not has_key and not has_stamp:
        report["warnings"].append("no respondent_key or submitted_at: identical answer rows were all kept, because they"
                                  " cannot be told apart from two people giving the same answers")
    changes = {}
    if fielded_from:
        changes["fielded_from"] = check_date(fielded_from, "fielded_from")
    if fielded_to:
        changes["fielded_to"] = check_date(fielded_to, "fielded_to")
    if distributed_via:
        changes["distributed_via"] = distributed_via
    if changes:
        store.update("surveys", survey_id, changes)
    store.audit("import", "surveys", survey_id, {"batch": batch, "read": report["read"], "valid": report["valid"],
                                                 "excluded": report["excluded"]})
    return report


def exclude_response(store, response_id, reason):
    if not (reason or "").strip():
        raise StoreError("excluding a response needs a reason; the response stays in the record")
    r = store.one("SELECT * FROM survey_responses WHERE id = ?", (response_id,))
    if r is None:
        raise StoreError("no survey response %r" % response_id)
    if r["excluded_reason"]:
        raise StoreError("response %s is already excluded (%s)" % (response_id, r["excluded_reason"]))
    store.update("survey_responses", response_id, {"excluded_reason": "manual: " + reason.strip()}, action="exclude")


def valid_responses(store, survey_id):
    return [json.loads(r["answers_json"]) for r in store.rows(
        "SELECT answers_json FROM survey_responses WHERE survey_id = ? AND excluded_reason IS NULL ORDER BY id", (survey_id,))]


def matches(answer, match):
    """Does one answer satisfy a match spec? {'in': [...]}, {'gte': x}, {'lte': x}, {'eq': x}; keys combine with AND."""
    if answer in (None, []):
        return False
    ok = True
    if "in" in match:
        got = set(answer) if isinstance(answer, list) else {answer}
        ok = ok and bool(got & set(match["in"]))
    for op, test in (("gte", lambda a, b: a >= b), ("lte", lambda a, b: a <= b), ("eq", lambda a, b: a == b)):
        if op in match:
            try:
                ok = ok and test(float(answer), float(match[op]))
            except (TypeError, ValueError):
                ok = ok and op == "eq" and answer == match[op]
    return ok


def count_matching(store, survey_id, question, match, among=None):
    """(k, n): valid respondents matching, out of valid respondents who answered (optionally within a subgroup)."""
    k = n = 0
    for a in valid_responses(store, survey_id):
        if among and not matches(a.get(among["question"]), {x: among[x] for x in among if x != "question"}):
            continue
        if a.get(question) in (None, []):
            continue
        n += 1
        if matches(a.get(question), match):
            k += 1
    return k, n


def analyse_survey(store, survey_id):
    sv = store.get("surveys", survey_id, "survey")
    inst = json.loads(sv["instrument_json"])
    total = store.one("SELECT COUNT(*) AS n FROM survey_responses WHERE survey_id = ?", (survey_id,))["n"]
    excluded = {r["reason"]: r["n"] for r in store.rows(
        "SELECT CASE WHEN excluded_reason LIKE 'manual:%' THEN 'manual' ELSE excluded_reason END AS reason, COUNT(*) AS n"
        " FROM survey_responses WHERE survey_id = ? AND excluded_reason IS NOT NULL GROUP BY 1", (survey_id,))}
    rows = valid_responses(store, survey_id)
    questions = []
    for q in inst["questions"]:
        answered = [a[q["id"]] for a in rows if a.get(q["id"]) not in (None, [])]
        item = {"id": q["id"], "text": q["text"], "kind": q["kind"], "type": q["type"], "n": len(answered)}
        if q["type"] in ("single", "multi"):
            item["options"] = []
            for o in q["options"]:
                k = sum(1 for a in answered if (o in a if isinstance(a, list) else a == o))
                lo, hi = stats.wilson(k, len(answered))
                item["options"].append({"option": o, "k": k, "share": stats.rate(k, len(answered)), "low": lo, "high": hi})
        elif q["type"] == "number":
            q1, med, q3 = stats.quartiles(answered)
            item.update({"median": med, "q1": q1, "q3": q3})
        else:
            item["texts"] = answered[:50]
        questions.append(item)
    return {"id": sv["id"], "title": sv["title"], "population": sv["population"], "distributed_via": sv["distributed_via"],
            "fielded_from": sv["fielded_from"], "fielded_to": sv["fielded_to"], "received": total, "valid": len(rows),
            "excluded": excluded, "questions": questions,
            "representative": "Not established. %d valid answers from people reached via %s. Nothing here shows they"
                              " mirror the whole market." % (len(rows), sv["distributed_via"] or "an unrecorded channel")}


def survey_prices(store, survey_id):
    """Price answers from a real survey: Van Westendorp rows and Gabor-Granger max prices, if the instrument has them."""
    sv = store.get("surveys", survey_id, "survey")
    inst = json.loads(sv["instrument_json"])
    rows = valid_responses(store, survey_id)
    out = {"van_westendorp": [], "gabor_granger": []}
    vw = inst.get("van_westendorp")
    if vw:
        for a in rows:
            r = tuple(a.get(vw[k]) for k in ("too_cheap", "cheap", "expensive", "too_expensive"))
            if all(isinstance(v, (int, float)) and v > 0 for v in r) and r[0] <= r[1] <= r[2] <= r[3]:
                out["van_westendorp"].append(r)
    gg = inst.get("gabor_granger")
    if gg:
        out["gabor_granger"] = [a[gg["question"]] for a in rows if isinstance(a.get(gg["question"]), (int, float))]
    return out
