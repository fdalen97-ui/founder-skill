"""The evidence store for founder-validate. Standard library only, no network.

One SQLite file per business idea (founder/validation/validation.db). The schema
keeps four families of data in separate tables and never lets a row move between
them:

    synthetic     syn_runs, syn_personas, syn_responses          (AI-generated)
    respondents   participants, interviews, interview_extracts,  (real people said)
                  surveys, survey_responses
    behaviour     experiments, behavior_events                   (real people did)
    transactions  transactions                                   (real people paid)

Claims about the business sit on top, each backed by evidence items. Every
evidence item carries one of seven categories and must point at a row in the
table that category belongs to. The database refuses anything else:

    A  AI-generated hypothesis or founder assumption   (no underlying record)
    B  synthetic customer response                     -> syn_runs
    C  external market research                        -> research_sources
    D  actual customer interview                       -> interview_extracts
    E  actual survey response                          -> surveys
    F  observed customer behaviour                     -> experiments
    G  actual purchase or financial commitment         -> transactions

An evidence item's category, reference, claim and stance can never be edited and
the row can never be deleted (SQLite triggers). To change your mind you retract
it with a reason, and the retraction stays in the record. Every write is logged
in a hash-chained audit table that can also not be edited.

What this does and does not protect against: the constraints and triggers stop
the tool, and anyone using ordinary SQL on the file, from blurring categories or
quietly removing a finding. The hash chain shows when audit entries were edited
or removed. Neither stops someone with the file and the intent to rewrite it
wholesale (drop the triggers, rebuild the chain). It is a record that resists
self-deception and casual edits, not a notarised ledger.
"""

import datetime
import hashlib
import json
import math
import os
import re
import sqlite3

SCHEMA_VERSION = 2

CATEGORIES = {
    "A": "AI-generated hypothesis or assumption",
    "B": "Synthetic customer response",
    "C": "External market research",
    "D": "Actual customer interview",
    "E": "Actual survey response",
    "F": "Observed customer behaviour",
    "G": "Actual purchase or financial commitment",
}
# What kind of knowledge a category is, in the founder's words.
KNOWLEDGE = {
    "A": "what we assume",
    "B": "what AI predicts",
    "C": "what external research indicates",
    "D": "what actual customers tell us",
    "E": "what actual customers tell us",
    "F": "what actual customers do",
    "G": "what customers actually pay for",
}
SYNTHETIC = ("A", "B")
REAL = ("D", "E", "F", "G")
CATEGORY_TABLE = {"A": None, "B": "syn_runs", "C": "research_sources", "D": "interview_extracts",
                  "E": "surveys", "F": "experiments", "G": "transactions"}

AREAS = ("market", "problem", "product", "commercial", "distribution")
DIMENSIONS = ("problem", "solution", "demand", "behavior", "payment", "segment", "economics")
STANCES = ("supports", "contradicts")
ROLES = ("user", "buyer", "budget_owner", "procurement", "influencer", "unknown")
PARTICIPANT_STATUS = ("invited", "screened_in", "screened_out", "scheduled", "interviewed", "no_show", "withdrawn")
GUIDE_TYPES = ("problem_discovery", "solution_testing", "pricing", "purchasing", "post_purchase")
EXTRACT_KINDS = ("statement", "behavior", "spend", "unmet_need", "objection", "trigger", "alternative", "contradiction")
PAST_BEHAVIOUR_KINDS = ("behavior", "spend")
QUESTION_KINDS = ("screening", "behavioral", "stated", "pricing", "demographic", "open")
EXPERIMENT_TYPES = ("landing_page", "price_test", "preorder", "concierge", "pilot", "ab_test")
EXPERIMENT_STATUS = ("designed", "running", "completed", "abandoned")
TRANSACTION_KINDS = ("deposit", "payment", "repeat_payment", "contract_signed", "refund", "cancellation")
MONEY_IN = ("deposit", "payment", "repeat_payment", "contract_signed")
MONEY_OUT = ("refund", "cancellation")
RESEARCH_KINDS = ("report", "statistic", "competitor_price", "review", "forum", "article", "other")


class StoreError(Exception):
    pass


def _in(col, values):
    return "%s IN (%s)" % (col, ", ".join("'%s'" % v for v in values))


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE concepts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
  price_point REAL, currency TEXT, created_at TEXT NOT NULL);

CREATE TABLE segments (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, definition TEXT NOT NULL,
  criteria TEXT NOT NULL DEFAULT '', basis TEXT NOT NULL CHECK (basis IN ('assumption', 'evidence')),
  basis_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);

CREATE TABLE hypotheses (
  id TEXT PRIMARY KEY, area TEXT NOT NULL CHECK (%(areas)s), statement TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('founder', 'ai')),
  impact INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5),
  uncertainty INTEGER NOT NULL CHECK (uncertainty BETWEEN 1 AND 5),
  test_cost INTEGER NOT NULL CHECK (test_cost BETWEEN 1 AND 5),
  test_time INTEGER NOT NULL CHECK (test_time BETWEEN 1 AND 5),
  if_false TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
  concept_id TEXT REFERENCES concepts(id), segment_id TEXT REFERENCES segments(id),
  retired_at TEXT, retire_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE hypothesis_versions (
  hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id), version INTEGER NOT NULL,
  statement TEXT NOT NULL, impact INTEGER NOT NULL, uncertainty INTEGER NOT NULL,
  test_cost INTEGER NOT NULL, test_time INTEGER NOT NULL, if_false TEXT NOT NULL,
  changed_at TEXT NOT NULL, reason TEXT NOT NULL,
  PRIMARY KEY (hypothesis_id, version));

CREATE TABLE claims (
  id TEXT PRIMARY KEY, description TEXT NOT NULL, dimension TEXT NOT NULL CHECK (%(dimensions)s),
  hypothesis_id TEXT REFERENCES hypotheses(id), concept_id TEXT REFERENCES concepts(id),
  segment_id TEXT REFERENCES segments(id), implications TEXT NOT NULL DEFAULT '',
  next_experiment TEXT NOT NULL DEFAULT '', limitations TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id),
  stance TEXT NOT NULL CHECK (%(stances)s),
  category TEXT NOT NULL CHECK (category IN ('A','B','C','D','E','F','G')),
  ref_table TEXT, ref_json TEXT NOT NULL DEFAULT '{}',
  method TEXT NOT NULL, collected_on TEXT NOT NULL, segment_id TEXT REFERENCES segments(id),
  summary TEXT NOT NULL, limitations TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL CHECK (origin IN ('founder', 'ai')),
  retracted_at TEXT, retract_reason TEXT, created_at TEXT NOT NULL,
  CHECK ((category = 'A' AND ref_table IS NULL)
      OR (category = 'B' AND ref_table = 'syn_runs')
      OR (category = 'C' AND ref_table = 'research_sources')
      OR (category = 'D' AND ref_table = 'interview_extracts')
      OR (category = 'E' AND ref_table = 'surveys')
      OR (category = 'F' AND ref_table = 'experiments')
      OR (category = 'G' AND ref_table = 'transactions')));

CREATE TABLE research_sources (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (%(research_kinds)s), title TEXT NOT NULL,
  url TEXT NOT NULL, publisher TEXT NOT NULL DEFAULT '', published_on TEXT, accessed_on TEXT NOT NULL,
  excerpt TEXT NOT NULL DEFAULT '', price REAL, currency TEXT, price_includes TEXT,
  notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);

-- synthetic ------------------------------------------------------------------
CREATE TABLE syn_runs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('lab', 'imported_panel')),
  model TEXT NOT NULL, prompt_version TEXT NOT NULL, persona_method TEXT NOT NULL,
  seed INTEGER, n_personas INTEGER NOT NULL, repeats INTEGER NOT NULL DEFAULT 1,
  scenario TEXT NOT NULL, assumptions TEXT NOT NULL DEFAULT '', stimulus_sha256 TEXT NOT NULL,
  arms_json TEXT NOT NULL DEFAULT '[]', concept_id TEXT REFERENCES concepts(id), created_at TEXT NOT NULL);

CREATE TABLE syn_personas (
  run_id TEXT NOT NULL REFERENCES syn_runs(id), persona_id TEXT NOT NULL, archetype TEXT NOT NULL,
  arm TEXT, card_json TEXT NOT NULL, PRIMARY KEY (run_id, persona_id));

CREATE TABLE syn_responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, persona_id TEXT NOT NULL,
  stage TEXT NOT NULL, repeat INTEGER NOT NULL DEFAULT 1, answer_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (run_id, persona_id, stage, repeat),
  FOREIGN KEY (run_id, persona_id) REFERENCES syn_personas(run_id, persona_id));

-- real respondents -----------------------------------------------------------
CREATE TABLE participants (
  id TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '', segment_id TEXT REFERENCES segments(id),
  role TEXT NOT NULL DEFAULT 'unknown' CHECK (%(roles)s),
  recruited_via TEXT NOT NULL DEFAULT '', status TEXT NOT NULL CHECK (%(pstatus)s),
  consent TEXT NOT NULL DEFAULT 'none' CHECK (consent IN ('none', 'recorded')),
  consent_on TEXT, consent_scope TEXT NOT NULL DEFAULT '', characteristics TEXT NOT NULL DEFAULT '',
  redacted_at TEXT, created_at TEXT NOT NULL);

CREATE TABLE interviews (
  id TEXT PRIMARY KEY, participant_id TEXT NOT NULL REFERENCES participants(id),
  guide_type TEXT NOT NULL CHECK (%(guides)s), conducted_on TEXT NOT NULL,
  interviewer TEXT NOT NULL DEFAULT '', medium TEXT NOT NULL DEFAULT '',
  record_kind TEXT NOT NULL CHECK (record_kind IN ('transcript', 'notes')),
  record_path TEXT, record_sha256 TEXT, concept_id TEXT REFERENCES concepts(id), created_at TEXT NOT NULL);

CREATE TABLE interview_extracts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, interview_id TEXT NOT NULL REFERENCES interviews(id),
  kind TEXT NOT NULL CHECK (%(ekinds)s), text TEXT NOT NULL,
  verbatim INTEGER NOT NULL CHECK (verbatim IN (0, 1)),
  author TEXT NOT NULL CHECK (author IN ('founder', 'ai')), theme TEXT NOT NULL DEFAULT '',
  amount REAL, currency TEXT, redacted_at TEXT, created_at TEXT NOT NULL);

CREATE TABLE surveys (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, instrument_json TEXT NOT NULL,
  population TEXT NOT NULL, distributed_via TEXT NOT NULL DEFAULT '',
  fielded_from TEXT, fielded_to TEXT, concept_id TEXT REFERENCES concepts(id),
  segment_id TEXT REFERENCES segments(id), created_at TEXT NOT NULL);

CREATE TABLE survey_responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, survey_id TEXT NOT NULL REFERENCES surveys(id),
  respondent_key TEXT, submitted_at TEXT, duration_s REAL, answers_json TEXT NOT NULL,
  row_sha256 TEXT NOT NULL, excluded_reason TEXT, import_batch TEXT NOT NULL, created_at TEXT NOT NULL);

-- behaviour ------------------------------------------------------------------
CREATE TABLE experiments (
  id TEXT PRIMARY KEY, type TEXT NOT NULL CHECK (%(xtypes)s), title TEXT NOT NULL,
  hypothesis_id TEXT REFERENCES hypotheses(id), concept_id TEXT REFERENCES concepts(id),
  segment_id TEXT REFERENCES segments(id), design_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (%(xstatus)s), registered_at TEXT NOT NULL, launched_at TEXT,
  completed_at TEXT, looks INTEGER NOT NULL DEFAULT 0, conclusion TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);

CREATE TABLE experiment_amendments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL REFERENCES experiments(id),
  at TEXT NOT NULL, change TEXT NOT NULL, reason TEXT NOT NULL);

CREATE TABLE behavior_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL REFERENCES experiments(id),
  variant TEXT NOT NULL DEFAULT 'all', event TEXT NOT NULL, count INTEGER NOT NULL CHECK (count >= 0),
  qualified INTEGER CHECK (qualified IN (0, 1)), occurred_on TEXT NOT NULL,
  traffic_source TEXT NOT NULL DEFAULT '', audience TEXT NOT NULL DEFAULT '', price_point REAL,
  cost REAL NOT NULL DEFAULT 0, origin_record TEXT NOT NULL, import_batch TEXT NOT NULL,
  voided_at TEXT, void_reason TEXT, created_at TEXT NOT NULL);

-- transactions ---------------------------------------------------------------
CREATE TABLE transactions (
  id TEXT PRIMARY KEY, experiment_id TEXT REFERENCES experiments(id),
  participant_id TEXT REFERENCES participants(id), payer_ref TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (%(tkinds)s), amount REAL NOT NULL CHECK (amount >= 0), currency TEXT NOT NULL,
  price_point REAL, variant TEXT NOT NULL DEFAULT 'all', occurred_on TEXT NOT NULL,
  reference TEXT NOT NULL, authorized INTEGER NOT NULL CHECK (authorized = 1),
  segment_id TEXT REFERENCES segments(id), voided_at TEXT, void_reason TEXT, created_at TEXT NOT NULL);

-- calibration ----------------------------------------------------------------
CREATE TABLE predictions (
  id TEXT PRIMARY KEY, source TEXT NOT NULL CHECK (source IN ('synthetic', 'founder', 'research')),
  run_id TEXT REFERENCES syn_runs(id), prediction_type TEXT NOT NULL, measured_what TEXT NOT NULL,
  predicted REAL NOT NULL, model TEXT NOT NULL DEFAULT '', scenario TEXT NOT NULL DEFAULT '',
  methodology TEXT NOT NULL DEFAULT '', segment_id TEXT REFERENCES segments(id),
  price_point REAL, made_at TEXT NOT NULL);

CREATE TABLE outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_id TEXT NOT NULL REFERENCES predictions(id),
  experiment_id TEXT NOT NULL REFERENCES experiments(id), measured_what TEXT NOT NULL,
  event TEXT NOT NULL, denominator TEXT NOT NULL, comparable INTEGER NOT NULL CHECK (comparable IN (0, 1)),
  comparable_note TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE (prediction_id, experiment_id));

-- audit ----------------------------------------------------------------------
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  tbl TEXT NOT NULL, row_id TEXT NOT NULL, detail_json TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);

""" % {
    "areas": _in("area", AREAS), "dimensions": _in("dimension", DIMENSIONS), "stances": _in("stance", STANCES),
    "research_kinds": _in("kind", RESEARCH_KINDS), "roles": _in("role", ROLES),
    "pstatus": _in("status", PARTICIPANT_STATUS), "guides": _in("guide_type", GUIDE_TYPES),
    "ekinds": _in("kind", EXTRACT_KINDS), "xtypes": _in("type", EXPERIMENT_TYPES),
    "xstatus": _in("status", EXPERIMENT_STATUS), "tkinds": _in("kind", TRANSACTION_KINDS),
}

TRIGGERS = """
-- integrity triggers ---------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS evidence_no_promote BEFORE UPDATE OF category, ref_table, ref_json, claim_id, stance, origin,
  method, collected_on, summary ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is immutable: retract it with a reason and add a new item'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is never deleted: retract it with a reason'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_unretract BEFORE UPDATE OF retracted_at, retract_reason ON evidence
  WHEN OLD.retracted_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a retraction is permanent: add a new evidence item instead'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'claims are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS syn_runs_frozen BEFORE UPDATE ON syn_runs
BEGIN SELECT RAISE(ABORT, 'a synthetic run record is frozen: start a new run'); END;
CREATE TRIGGER IF NOT EXISTS syn_runs_no_delete BEFORE DELETE ON syn_runs
BEGIN SELECT RAISE(ABORT, 'synthetic runs are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS syn_responses_frozen BEFORE UPDATE ON syn_responses
BEGIN SELECT RAISE(ABORT, 'synthetic responses are never edited'); END;
CREATE TRIGGER IF NOT EXISTS syn_responses_no_delete BEFORE DELETE ON syn_responses
BEGIN SELECT RAISE(ABORT, 'synthetic responses are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS experiment_design_locked BEFORE UPDATE OF design_json, type, hypothesis_id, registered_at ON experiments
  WHEN OLD.launched_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'the design is locked at launch: record an amendment'); END;
CREATE TRIGGER IF NOT EXISTS experiments_no_delete BEFORE DELETE ON experiments
BEGIN SELECT RAISE(ABORT, 'experiments are never deleted: abandon it with a reason'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON behavior_events
BEGIN SELECT RAISE(ABORT, 'behaviour events are never deleted: void them with a reason'); END;
CREATE TRIGGER IF NOT EXISTS events_frozen BEFORE UPDATE OF experiment_id, variant, event, count, qualified, occurred_on,
  traffic_source, price_point, cost, origin_record ON behavior_events
BEGIN SELECT RAISE(ABORT, 'behaviour events are never edited: void and re-record'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_delete BEFORE DELETE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are never deleted: void them with a reason'); END;
CREATE TRIGGER IF NOT EXISTS transactions_frozen BEFORE UPDATE OF experiment_id, payer_ref, kind, amount, currency, price_point,
  occurred_on, reference, authorized ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are never edited: void and re-record'); END;
CREATE TRIGGER IF NOT EXISTS responses_no_delete BEFORE DELETE ON survey_responses
BEGIN SELECT RAISE(ABORT, 'survey responses are never deleted: exclude them with a reason'); END;
CREATE TRIGGER IF NOT EXISTS responses_frozen BEFORE UPDATE OF survey_id, answers_json, row_sha256, respondent_key ON survey_responses
BEGIN SELECT RAISE(ABORT, 'survey answers are never edited'); END;
CREATE TRIGGER IF NOT EXISTS extracts_no_delete BEFORE DELETE ON interview_extracts
BEGIN SELECT RAISE(ABORT, 'interview extracts are never deleted: redact the participant instead'); END;
CREATE TRIGGER IF NOT EXISTS extracts_frozen BEFORE UPDATE OF interview_id, kind, verbatim, author ON interview_extracts
BEGIN SELECT RAISE(ABORT, 'an extract cannot change kind, author or verbatim status'); END;
CREATE TRIGGER IF NOT EXISTS extracts_text_frozen BEFORE UPDATE OF text ON interview_extracts
  WHEN NEW.redacted_at IS NULL
BEGIN SELECT RAISE(ABORT, 'extract text changes only through participant redaction'); END;
CREATE TRIGGER IF NOT EXISTS predictions_frozen BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'a prediction is frozen once recorded'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are never deleted, including the wrong ones'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_no_delete BEFORE DELETE ON outcomes
BEGIN SELECT RAISE(ABORT, 'calibration outcomes are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS claims_frozen BEFORE UPDATE OF dimension, description, hypothesis_id ON claims
BEGIN SELECT RAISE(ABORT, 'a claim cannot change its wording, question or hypothesis: add a new claim'); END;
CREATE TRIGGER IF NOT EXISTS experiment_launch_frozen BEFORE UPDATE OF launched_at ON experiments
  WHEN OLD.launched_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'the launch date is fixed once set'); END;
CREATE TRIGGER IF NOT EXISTS surveys_frozen BEFORE UPDATE OF instrument_json ON surveys
BEGIN SELECT RAISE(ABORT, 'a survey instrument is frozen once created: create a new survey'); END;
CREATE TRIGGER IF NOT EXISTS surveys_no_delete BEFORE DELETE ON surveys
BEGIN SELECT RAISE(ABORT, 'surveys are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_frozen BEFORE UPDATE ON outcomes
BEGIN SELECT RAISE(ABORT, 'a calibration outcome is frozen once recorded'); END;
CREATE TRIGGER IF NOT EXISTS responses_no_unexclude BEFORE UPDATE OF excluded_reason ON survey_responses
  WHEN OLD.excluded_reason IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'an excluded response stays excluded'); END;
CREATE TRIGGER IF NOT EXISTS events_no_unvoid BEFORE UPDATE OF voided_at, void_reason ON behavior_events
  WHEN OLD.voided_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a voided event stays voided'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_unvoid BEFORE UPDATE OF voided_at, void_reason ON transactions
  WHEN OLD.voided_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a voided transaction stays voided'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_replace BEFORE INSERT ON evidence WHEN EXISTS (SELECT 1 FROM evidence WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_replace BEFORE INSERT ON claims WHEN EXISTS (SELECT 1 FROM claims WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_replace BEFORE INSERT ON audit_log WHEN EXISTS (SELECT 1 FROM audit_log WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS syn_runs_no_replace BEFORE INSERT ON syn_runs WHEN EXISTS (SELECT 1 FROM syn_runs WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS syn_responses_no_replace BEFORE INSERT ON syn_responses WHEN EXISTS (SELECT 1 FROM syn_responses WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_replace BEFORE INSERT ON predictions WHEN EXISTS (SELECT 1 FROM predictions WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_no_replace BEFORE INSERT ON outcomes WHEN EXISTS (SELECT 1 FROM outcomes WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS behavior_events_no_replace BEFORE INSERT ON behavior_events WHEN EXISTS (SELECT 1 FROM behavior_events WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_replace BEFORE INSERT ON transactions WHEN EXISTS (SELECT 1 FROM transactions WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS survey_responses_no_replace BEFORE INSERT ON survey_responses WHEN EXISTS (SELECT 1 FROM survey_responses WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS interview_extracts_no_replace BEFORE INSERT ON interview_extracts WHEN EXISTS (SELECT 1 FROM interview_extracts WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS experiments_no_replace BEFORE INSERT ON experiments WHEN EXISTS (SELECT 1 FROM experiments WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS surveys_no_replace BEFORE INSERT ON surveys WHEN EXISTS (SELECT 1 FROM surveys WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS interviews_no_replace BEFORE INSERT ON interviews WHEN EXISTS (SELECT 1 FROM interviews WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS hypotheses_no_replace BEFORE INSERT ON hypotheses WHEN EXISTS (SELECT 1 FROM hypotheses WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS research_sources_no_replace BEFORE INSERT ON research_sources WHEN EXISTS (SELECT 1 FROM research_sources WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a row with this id already exists and cannot be replaced'); END;
"""

ID_PREFIX = {"concepts": "K", "segments": "SEG", "hypotheses": "H", "claims": "C", "evidence": "E",
             "research_sources": "SRC", "syn_runs": "R", "participants": "PT", "interviews": "IV",
             "surveys": "SV", "experiments": "X", "transactions": "T", "predictions": "P"}


def now():
    """UTC timestamp. FOUNDER_VALIDATE_NOW overrides it (tests, backfilled imports are still stamped today)."""
    fixed = os.environ.get("FOUNDER_VALIDATE_NOW")
    if fixed:
        return fixed
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return now()[:10]


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}($|[T ])")


def check_date(value, field):
    text = str(value)
    try:
        if not _DATE.match(text):
            raise ValueError(text)
        datetime.date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        raise StoreError("%s must be a date like 2026-03-14 (got %r)" % (field, value))
    return text[:10]


MATCH_OPS = ("in", "gte", "lte", "eq")


def check_match(spec, what, need_question=False):
    """Validate a survey match spec. An unknown key would silently match everyone, so it is refused."""
    if not isinstance(spec, dict) or not spec:
        raise StoreError("%s must be an object such as {\"in\": [\"Weekly\"]} or {\"gte\": 50}" % what)
    ops = {k: v for k, v in spec.items() if k != "question"}
    if need_question and not isinstance(spec.get("question"), str):
        raise StoreError("%s needs 'question': the question id that defines the subgroup" % what)
    if not need_question and "question" in spec:
        raise StoreError("%s takes no 'question' key" % what)
    unknown = sorted(set(ops) - set(MATCH_OPS))
    if unknown or not ops:
        raise StoreError("%s accepts only %s (got %s)" % (what, ", ".join(MATCH_OPS), ", ".join(unknown) or "nothing"))
    if "in" in ops and (not isinstance(ops["in"], list) or not ops["in"] or not all(isinstance(x, str) for x in ops["in"])):
        raise StoreError("%s: 'in' must be a non-empty list of answer options" % what)
    for op in ("gte", "lte"):
        if op in ops and (isinstance(ops[op], bool) or not isinstance(ops[op], (int, float))):
            raise StoreError("%s: '%s' must be a number" % (what, op))
    if "eq" in ops and (isinstance(ops["eq"], bool) or not isinstance(ops["eq"], (int, float, str))):
        raise StoreError("%s: 'eq' must be a number or a string" % what)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Store(object):
    """A thin, strict wrapper around the SQLite file. All writes go through here and are audited."""

    def __init__(self, directory, create=False, actor=None):
        self.dir = directory
        self.path = os.path.join(directory, "validation.db")
        exists = os.path.exists(self.path)
        if not exists and not create:
            raise StoreError("no validation project in %s: run 'validate.py init' first" % directory)
        os.makedirs(directory, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.actor = actor or os.environ.get("FOUNDER_VALIDATE_ACTOR") or "founder"
        if not exists:
            self.db.executescript(SCHEMA)
            self.db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            self.db.execute("INSERT INTO meta VALUES ('created_at', ?)", (now(),))
        self.db.executescript(TRIGGERS)      # idempotent: an older record gains any guard added since it was created
        self.db.commit()

    def close(self):
        self.db.close()

    # ── helpers ────────────────────────────────────────────────────────────────
    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value))
        self.audit("set", "meta", key, {"value": value})

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def get(self, table, row_id, what=None):
        r = self.one("SELECT * FROM %s WHERE id = ?" % table, (row_id,))
        if r is None:
            raise StoreError("no %s %r" % (what or table.rstrip("s"), row_id))
        return r

    def next_id(self, table):
        n = self.db.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        return "%s%03d" % (ID_PREFIX[table], n + 1)

    def audit(self, action, table, row_id, detail=None):
        prev = self.db.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else ""
        at = now()
        detail_json = canonical(detail or {})
        digest = sha256_text("|".join([prev_hash, at, self.actor, action, table, str(row_id), detail_json]))
        self.db.execute("INSERT INTO audit_log (at, actor, action, tbl, row_id, detail_json, prev_hash, hash)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (at, self.actor, action, table, str(row_id), detail_json, prev_hash, digest))

    def verify_audit(self):
        """Recompute the hash chain. Returns (ok, entries, first_bad_id)."""
        prev = ""
        n = 0
        for r in self.db.execute("SELECT * FROM audit_log ORDER BY id"):
            n += 1
            digest = sha256_text("|".join([prev, r["at"], r["actor"], r["action"], r["tbl"], r["row_id"], r["detail_json"]]))
            if r["prev_hash"] != prev or r["hash"] != digest:
                return False, n, r["id"]
            prev = r["hash"]
        return True, n, None

    def insert(self, table, row, auto_id=True):
        """Insert one row, audit it, return its id."""
        row = dict(row)
        if auto_id and table in ID_PREFIX:
            row["id"] = self.next_id(table)
        if "created_at" in self._columns(table) and "created_at" not in row:
            row["created_at"] = now()
        cols = sorted(row)
        try:
            cur = self.db.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(cols), ", ".join("?" * len(cols))),
                                  [row[c] for c in cols])
        except sqlite3.IntegrityError as e:
            raise StoreError("%s refused: %s" % (table, e))
        rid = row.get("id", cur.lastrowid)
        self.audit("insert", table, rid, {k: v for k, v in row.items() if k not in ("created_at",)})
        return rid

    def update(self, table, row_id, changes, action="update"):
        cols = sorted(changes)
        try:
            self.db.execute("UPDATE %s SET %s WHERE id = ?" % (table, ", ".join("%s = ?" % c for c in cols)),
                            [changes[c] for c in cols] + [row_id])
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            raise StoreError("%s refused: %s" % (table, e))
        self.audit(action, table, row_id, changes)

    def _columns(self, table):
        return [r[1] for r in self.db.execute("PRAGMA table_info(%s)" % table)]

    def commit(self):
        self.db.commit()

    # ── project ────────────────────────────────────────────────────────────────
    def init_project(self, name, concept, price_point=None, currency=None):
        if self.meta("project_name"):
            raise StoreError("this folder already holds the project %r" % self.meta("project_name"))
        if not (name or "").strip() or not (concept or "").strip():
            raise StoreError("a project needs a name and a concept description")
        self.set_meta("project_name", name.strip())
        cid = self.add_concept({"name": name.strip(), "description": concept.strip(),
                                "price_point": price_point, "currency": currency})
        self.commit()
        return cid

    def add_concept(self, c):
        _need(c, ("name", "description"), "concept")
        return self.insert("concepts", {"name": c["name"], "description": c["description"],
                                        "price_point": _float(c.get("price_point"), "price_point"),
                                        "currency": c.get("currency")})

    def add_segment(self, s):
        _need(s, ("name", "definition"), "segment")
        basis = s.get("basis", "assumption")
        if basis == "evidence" and not (s.get("basis_note") or "").strip():
            raise StoreError("a segment whose basis is 'evidence' needs basis_note saying which evidence")
        return self.insert("segments", {"name": s["name"], "definition": s["definition"],
                                        "criteria": s.get("criteria", ""), "basis": basis,
                                        "basis_note": s.get("basis_note", "")})

    # ── hypotheses ─────────────────────────────────────────────────────────────
    def add_hypothesis(self, h):
        _need(h, ("area", "statement", "impact", "uncertainty", "test_cost", "test_time"), "hypothesis")
        row = {"area": h["area"], "statement": h["statement"].strip(), "origin": h.get("origin", "ai"),
               "impact": _score(h["impact"], "impact"), "uncertainty": _score(h["uncertainty"], "uncertainty"),
               "test_cost": _score(h["test_cost"], "test_cost"), "test_time": _score(h["test_time"], "test_time"),
               "if_false": h.get("if_false", ""), "concept_id": h.get("concept_id"),
               "segment_id": h.get("segment_id"), "updated_at": now()}
        hid = self.insert("hypotheses", row)
        self.insert("hypothesis_versions", {"hypothesis_id": hid, "version": 1, "statement": row["statement"],
                                            "impact": row["impact"], "uncertainty": row["uncertainty"],
                                            "test_cost": row["test_cost"], "test_time": row["test_time"],
                                            "if_false": row["if_false"], "changed_at": now(), "reason": "created"},
                    auto_id=False)
        return hid

    def revise_hypothesis(self, hid, changes, reason):
        if not (reason or "").strip():
            raise StoreError("revising a hypothesis needs a reason (the old version is kept)")
        h = self.get("hypotheses", hid, "hypothesis")
        new = dict(h)
        for k in ("statement", "if_false"):
            if k in changes:
                new[k] = changes[k]
        for k in ("impact", "uncertainty", "test_cost", "test_time"):
            if k in changes:
                new[k] = _score(changes[k], k)
        version = h["version"] + 1
        self.update("hypotheses", hid, {"statement": new["statement"], "if_false": new["if_false"],
                                        "impact": new["impact"], "uncertainty": new["uncertainty"],
                                        "test_cost": new["test_cost"], "test_time": new["test_time"],
                                        "version": version, "updated_at": now()}, action="revise")
        self.insert("hypothesis_versions", {"hypothesis_id": hid, "version": version, "statement": new["statement"],
                                            "impact": new["impact"], "uncertainty": new["uncertainty"],
                                            "test_cost": new["test_cost"], "test_time": new["test_time"],
                                            "if_false": new["if_false"], "changed_at": now(), "reason": reason},
                    auto_id=False)
        return version

    def retire_hypothesis(self, hid, reason):
        if not (reason or "").strip():
            raise StoreError("retiring a hypothesis needs a reason")
        self.get("hypotheses", hid, "hypothesis")
        self.update("hypotheses", hid, {"retired_at": now(), "retire_reason": reason}, action="retire")

    # ── claims and evidence ────────────────────────────────────────────────────
    def add_claim(self, c):
        _need(c, ("description", "dimension"), "claim")
        if c.get("hypothesis_id"):
            self.get("hypotheses", c["hypothesis_id"], "hypothesis")
        return self.insert("claims", {"description": c["description"].strip(), "dimension": c["dimension"],
                                      "hypothesis_id": c.get("hypothesis_id"), "concept_id": c.get("concept_id"),
                                      "segment_id": c.get("segment_id"), "implications": c.get("implications", ""),
                                      "next_experiment": c.get("next_experiment", ""),
                                      "limitations": c.get("limitations", "")})

    def add_evidence(self, e):
        """Attach one evidence item to a claim. The category decides which table it must point at."""
        _need(e, ("claim_id", "stance", "category", "summary"), "evidence")
        cat = e["category"]
        if cat not in CATEGORIES:
            raise StoreError("category must be one of A to G (got %r)" % cat)
        if not all(isinstance(e[k], str) for k in ("claim_id", "stance", "summary")):
            raise StoreError("claim_id, stance and summary must be text")
        self.get("claims", e["claim_id"], "claim")
        if e.get("ref") is not None and not isinstance(e["ref"], dict):
            raise StoreError("ref must be an object naming the underlying record")
        ref = dict(e.get("ref") or {})
        for key, kind in (("run", str), ("survey", str), ("question", str), ("experiment", str), ("event", str),
                          ("denominator", str), ("variant", str)):
            if key in ref and not isinstance(ref[key], kind):
                raise StoreError("ref.%s must be text" % key)
        for key, kind in (("sources", str), ("extracts", int), ("transactions", str)):
            if key in ref and (not isinstance(ref[key], list) or not all(
                    isinstance(x, kind) and not isinstance(x, bool) for x in ref[key])):
                raise StoreError("ref.%s must be a list of %s" % (key, "ids" if kind is str else "extract numbers"))
        table = CATEGORY_TABLE[cat]
        method, collected = e.get("method"), e.get("collected_on")
        if cat == "A":
            if ref:
                raise StoreError("category A is an assumption and has no underlying record; use the category of the record")
            method = method or "assumption (not collected)"
            collected = collected or today()
        elif cat == "B":
            run = self.get("syn_runs", ref.get("run"), "synthetic run")
            method = method or "synthetic panel (%s, %d simulated profiles)" % (run["model"], run["n_personas"])
            collected = collected or run["created_at"][:10]
        elif cat == "C":
            ids = ref.get("sources") or []
            if not ids:
                raise StoreError("category C needs ref.sources: at least one research source id")
            for sid in ids:
                self.get("research_sources", sid, "research source")
            method = method or "desk research"
            collected = collected or max(self.get("research_sources", s)["accessed_on"] for s in ids)
        elif cat == "D":
            ids = ref.get("extracts") or []
            if not ids:
                raise StoreError("category D needs ref.extracts: the interview extract ids it rests on")
            dates = []
            for xid in ids:
                x = self.one("SELECT x.id, i.conducted_on FROM interview_extracts x JOIN interviews i"
                             " ON i.id = x.interview_id WHERE x.id = ?", (xid,))
                if x is None:
                    raise StoreError("no interview extract %r" % xid)
                dates.append(x["conducted_on"])
            method = method or "customer interviews"
            collected = collected or max(dates)
        elif cat == "E":
            sv = self.get("surveys", ref.get("survey"), "survey")
            qids = {q["id"]: q for q in json.loads(sv["instrument_json"])["questions"]}
            if ref.get("question") not in qids:
                raise StoreError("category E needs ref.question: a question id from %s" % sv["id"])
            check_match(ref.get("match"), "ref.match")
            if "among" in ref:
                check_match(ref["among"], "ref.among", need_question=True)
                if ref["among"]["question"] not in qids:
                    raise StoreError("ref.among points at an unknown question %r" % ref["among"]["question"])
            method = method or "survey (%s)" % sv["distributed_via"]
            collected = collected or sv["fielded_to"] or sv["created_at"][:10]
        elif cat == "F":
            x = self.get("experiments", ref.get("experiment"), "experiment")
            if x["launched_at"] is None:
                raise StoreError("experiment %s has not launched, so it has observed nothing yet" % x["id"])
            if not ref.get("event"):
                raise StoreError("category F needs ref.event: the observed action being counted")
            metric = json.loads(x["design_json"])["primary_metric"]
            if ref["event"] == metric["denominator"]:
                raise StoreError("'%s' is the denominator of %s: being exposed to the offer is not an action. Count the"
                                 " action people took (for example '%s')." % (ref["event"], x["id"], metric["event"]))
            if e["stance"] == "contradicts" and not ref.get("denominator"):
                raise StoreError("behaviour evidence against a claim needs ref.denominator, so the people who saw the"
                                 " offer and did not act can be counted")
            method = method or "%s experiment" % x["type"].replace("_", " ")
            collected = collected or (x["completed_at"] or today())[:10]
        elif cat == "G":
            if ref.get("transactions"):
                for tid in ref["transactions"]:
                    self.get("transactions", tid, "transaction")
            elif ref.get("experiment"):
                self.get("experiments", ref["experiment"], "experiment")
            else:
                raise StoreError("category G needs ref.transactions (ids) or ref.experiment")
            method = method or "recorded transactions"
            collected = collected or today()
        return self.insert("evidence", {
            "claim_id": e["claim_id"], "stance": e["stance"], "category": cat, "ref_table": table,
            "ref_json": canonical(ref), "method": method, "collected_on": check_date(collected, "collected_on"),
            "segment_id": e.get("segment_id"), "summary": e["summary"].strip(),
            "limitations": e.get("limitations", ""), "origin": e.get("origin", "ai")})

    def retract_evidence(self, eid, reason):
        if not (reason or "").strip():
            raise StoreError("a retraction needs a reason; it stays visible in the record")
        self.get("evidence", eid, "evidence item")
        self.update("evidence", eid, {"retracted_at": now(), "retract_reason": reason}, action="retract")

    def add_research_source(self, s):
        _need(s, ("title", "url"), "research source")
        if not str(s["url"]).startswith(("http://", "https://")) and not os.path.exists(str(s["url"])):
            raise StoreError("a research source needs a real link (http...) or a path to a file you have")
        return self.insert("research_sources", {
            "kind": s.get("kind", "other"), "title": s["title"], "url": s["url"],
            "publisher": s.get("publisher", ""), "published_on": s.get("published_on"),
            "accessed_on": check_date(s.get("accessed_on") or today(), "accessed_on"),
            "excerpt": s.get("excerpt", ""), "price": _float(s.get("price"), "price"),
            "currency": s.get("currency"), "price_includes": s.get("price_includes"), "notes": s.get("notes", "")})


def _need(obj, keys, what):
    if not isinstance(obj, dict):
        raise StoreError("%s must be a JSON object" % what)
    for k in keys:
        if obj.get(k) in (None, "", []):
            raise StoreError("%s needs '%s'" % (what, k))


def _score(v, field):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise StoreError("%s must be a whole number from 1 to 5" % field)
    if not 1 <= v <= 5:
        raise StoreError("%s must be from 1 to 5 (got %d)" % (field, v))
    return v


def _float(v, field):
    if v in (None, ""):
        return None
    try:
        if isinstance(v, bool):
            raise ValueError(v)
        v = float(v)
        if not math.isfinite(v):
            raise ValueError(v)
        return v
    except (TypeError, ValueError):
        raise StoreError("%s must be a number (got %r)" % (field, v))
