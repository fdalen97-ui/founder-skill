---
name: founder-validate
description: >-
  The market validation engine. Keeps one evidence record per business idea and
  tells the founder whether the problem is real, whether the right customers want
  the solution, whether they will pay, whether it can be done profitably, and what
  the cheapest next experiment is. Separates what is assumed, what AI predicts,
  what research indicates, what customers say, what they do and what they pay
  for, and never lets one pass for another: synthetic panels only generate
  questions, real interviews, surveys, experiments and payments are imported with
  provenance, and the grades are computed from real evidence only. Use when the
  user says "validate my business idea", "is there real demand", "is this
  validated", "what should I test next", "customer interviews", "run a survey",
  "landing page test", "pre-orders", "pilot", "go or no-go", or "market
  validation report".
argument-hint: "[status | next | report | the business idea]"
---

# founder-validate

The other skills in the pack tell a founder what might work. This one keeps the
record of what has actually been shown, and by whom. Its whole job is to stop a
founder building something nobody wants.

What the user typed after `/founder-validate`: `$ARGUMENTS`

## The one rule

AI can help form a hypothesis. Only evidence collected from real people can
validate demand. So there are six kinds of knowing, and you say which one you are
using every time you speak:

| | kind of knowing | category in the record |
| --- | --- | --- |
| 1 | what we assume | A |
| 2 | what AI predicts | A (AI-drafted), B (synthetic panel) |
| 3 | what external research indicates | C |
| 4 | what actual customers tell us | D (interviews), E (surveys) |
| 5 | what actual customers do | F |
| 6 | what customers actually pay for | G |

A and B never move a grade. Not at 100 answers, not at 100,000.

## The tool

All bookkeeping goes through `validate.py` in this skill's folder:

```bash
python3 "${CLAUDE_SKILL_DIR}/validate.py" <command>
```

Below, `VALIDATE` means exactly that. State lives in `founder/validation/`
(`validation.db`, stored transcripts, synthetic runs, the report, the dashboard).
Records go in as JSON, with `--json <file>` or on standard input. The shapes are
in `${CLAUDE_SKILL_DIR}/references/evidence.md`. The tool refuses anything that
would blur the categories, so when it refuses, fix the input. Never work around
it by writing to the database yourself.

## What you must never do

- Never invent a respondent, a quote, a visitor, a signup or a payment, and never
  "fill in" a result that has not come back. If the founder has not done the
  interview, there is no interview.
- Never answer a synthetic brief yourself, and never present a synthetic answer
  as something a customer said.
- Never turn a synthetic stance or a survey intention into a conversion rate.
- Never say a sample is representative or a result is significant unless the tool
  says so.
- Never drop, soften or bury a negative finding. Contradicting evidence is
  recorded with the same care as supporting evidence.
- Never record a payment the customer did not explicitly authorise.
- Never store an interview without the participant's consent on record.

## Step 0: where things stand

If `founder/validation/validation.db` exists, run `VALIDATE status` and pick up
from the step it points at. `status`, `next` and `report` as the argument go
straight to steps 9 and 10. Otherwise start at step 1.

## Step 1: understand the business

Read `founder/idea.md` (and `competitors.md`, `customer.json`, `numbers.json` if
the pack has run). If there is no idea file, write one from the conversation
first, as `/founder-board` does. Then:

```bash
VALIDATE init --idea founder/idea.md --price <planned price> --currency <ISO code>
VALIDATE add segment --json segment.json
```

A segment needs `criteria` you could screen a stranger against ("writes 20 or
more reports a month", not "busy professionals"). Mark its `basis` as
`assumption` unless real evidence already defines it.

## Step 2: the hypothesis lab

List what must be true for the business to work, across five areas: **market**,
**problem**, **product**, **commercial**, **distribution**. The questions to cover
for each area are in `${CLAUDE_SKILL_DIR}/references/evidence.md`. For each
hypothesis, agree four scores with the founder, 1 to 5: `impact` if it is false,
current `uncertainty`, `test_cost`, `test_time`. Write `if_false`: what happens
to the business. Mark `origin` as `ai` when you drafted it, `founder` when they did.

```bash
VALIDATE add hypothesis --json hypotheses.json
VALIDATE next
```

`next` names the most important unanswered question (impact x uncertainty over
the effort to test) and the cheapest credible experiment for it. Say it to the
founder in one sentence. Hypotheses are versioned: change one with
`VALIDATE hypothesis revise H001 --json change.json --reason "..."`.

## Step 3: synthetic exploration

Optional, fast, and only for finding questions. Tell the founder before you
start: these are simulated profiles, the run costs one sub-agent call per profile
per stage, and nothing it produces is evidence.

Write the lab profile (`customer.json` plus a neutral `situation` and the
`alternatives` people use today) and the arms (`offer`, `price`, `scenario`; one
arm per thing being compared, everything else identical). Shapes are in
`${CLAUDE_SKILL_DIR}/references/evidence.md`. Then:

```bash
VALIDATE synth init --customer lab.json --arms arms.json --n 100 --model <the model the sub-agents run on> --repeats 1
VALIDATE synth briefs R001 --stage problem     # the situation only: no product, no price
VALIDATE synth briefs R001 --stage concept     # the plain offer, the alternatives, a buying moment
VALIDATE synth ingest R001
VALIDATE synth tally R001
```

`briefs` lists waves of 10. For each wave send ONE message with one Agent call
per brief (`subagent_type: general-purpose`, prompt: `Read <brief path> and
follow it exactly. It is your whole brief.`). Run the whole problem stage before
the concept stage. Use `--n 20` for a first look and `--repeats 2` to see how
much the answers wobble between runs. The tool deals nine dispositions by quota
(skeptics, people happy with what they have, people without the problem, people
who do not hold the budget...), caps enthusiasts, and refuses an offer written
in promotional language.

Read `founder/validation/synth/R001/results.md` to the founder as: objections,
reasons to reject, other uses, who decides and who pays, and the questions to
take to real people. Turn the suggested hypotheses into category A hypotheses.
Do not read out a "buy rate": there is none. An existing `/founder-consumer`
panel can be put on the record with `VALIDATE synth import-panel`.

## Step 4: say what remains unproven

Run `VALIDATE status`. After steps 1 to 3 every grade is still Unknown. Say so
plainly: "Nothing is validated yet. We have assumptions and simulated answers.
Here is the first real test." Then `VALIDATE next`.

## Step 5: real customer research

Follow `${CLAUDE_SKILL_DIR}/references/interviews.md` and
`${CLAUDE_SKILL_DIR}/references/surveys.md`. In short:

1. **Recruit.** Write the recruitment criteria, a screener, outreach messages,
   the invitation, the thank-you incentive and a target per segment
   (`VALIDATE recruit --json targets.json`). The founder sends them. Add a
   participant only when a real person exists (`VALIDATE add participant`), and
   record their consent before storing anything they said.
2. **Interview.** Write the guide for the stage (problem discovery, solution
   testing, pricing, purchasing, post-purchase), then lint it:
   `VALIDATE guide lint guide.md --type problem_discovery`. Fix every flag.
   Questions are about the last time it happened, what they did and what it cost.
3. **File it.** The founder gives you a transcript or their notes. The tool does
   not transcribe audio: ask for a transcript from whatever tool they use.
   `VALIDATE add interview`, then one `VALIDATE add extract` per finding:
   statements, past behaviour, spend, unmet needs, objections, triggers,
   alternatives, contradictions. Set `verbatim: true` only for the customer's
   exact words; the tool checks each quote against the transcript and refuses a
   paraphrase. Everything else is a summary and is labelled as yours.
4. **Survey.** Build the instrument JSON, `VALIDATE survey create`, then
   `VALIDATE survey form SV001 --out survey.md` for a form the founder builds in
   their own survey tool. When answers are in: `VALIDATE survey import SV001
   --csv export.csv --via "<how it was distributed>"`. Exclusions (duplicates,
   incomplete, screened out, too fast) are applied by rule and kept on record.

## Step 6: behavioural evidence

Move from what people say to what they do. Follow
`${CLAUDE_SKILL_DIR}/references/experiments.md` for the six experiment types
(landing page, price test, pre-order or deposit, concierge MVP, B2B pilot, A/B
test). The design is written and registered before launch:

```bash
VALIDATE experiment plan-sample --type landing_page --baseline 0.05 --margin 0.03
VALIDATE experiment register --json design.json
VALIDATE experiment launch X001
VALIDATE experiment import X001 --csv events.csv        # or: experiment record X001 --json events.json
VALIDATE add transaction --json payment.json            # only real, authorised, with a receipt reference
VALIDATE experiment read X001
VALIDATE experiment complete X001 --conclusion "..."
```

Every event row says whether the traffic was qualified. Unknown is allowed and
is left out of the rate. Before the founder sees a result, record what the
synthetic run or the founder predicted (`VALIDATE synth predict R001 --arm A`, or
`VALIDATE add prediction`), then link the two with `VALIDATE add outcome` so the
gap is on the record.

## Step 7: turn findings into claims

For each thing learned, add a claim (the statement, the question it bears on,
the hypothesis, business implications, the next experiment) and attach evidence
for AND against it:

```bash
VALIDATE add claim --json claim.json
VALIDATE add evidence --json evidence.json
```

Each evidence item names its category and points at the underlying record:
interview extracts, a survey question, an experiment event, transactions, a
research source with its link, a synthetic run. The tool counts the real units
itself. If the founder changes their mind, `VALIDATE retract E003 --reason "..."`
keeps the item visible as retracted.

## Step 8: read the analysis back

`VALIDATE status`, `VALIDATE pricing` and `VALIDATE calibration`. When you
present them:

- Give the number and kind of real people behind every finding ("6 of 8
  interviewed adjusters", never "customers").
- Keep stated intentions apart from past behaviour and from actions.
- When a prediction and a result differ (70% simulated interest, 8% of 250
  qualified visitors asking for a demo), do not average them and do not explain
  the gap away. They measure different things. Go through the possible reasons
  the tool lists and say which the evidence supports.
- Calibration figures appear only after five comparable prediction/result pairs.
  Before that, say the system is not calibrated.

## Step 9: validation status

Seven questions, each graded from real evidence: problem, solution, demand,
behaviour, payment, segment, economics. Each is Unknown, Weakly supported,
Moderately supported, Strongly supported or Contradicted by evidence, with its
limitations and what is missing. There is no overall score and you must not
compute one. Explain a grade in plain words: what counted, what did not and why.

## Step 10: the report, the dashboard, the next step

```bash
VALIDATE report        # founder/validation/validation-report.md, 17 sections
VALIDATE dashboard     # founder/validation/dashboard.html, one file, opens in a browser
VALIDATE export        # every table as CSV, grouped by data family
VALIDATE audit         # verifies the audit trail
```

The recommendation is Go, Conditional Go, No-Go, or "No recommendation yet" when
there is too little real evidence to say either way. It is computed. Never write
it by hand. End every session with the one next experiment from `VALIDATE next`,
its cost, its time, and what each outcome would mean. Do not recommend building
the product while the problem and qualified demand are below moderate.

## Honest limits, say them once

- The tool cannot reach customers. It has no survey, analytics, payment or
  transcription integration: data comes in as files the founder exports. If the
  marketing skills pack is installed, its tool guides (GA4, PostHog, Stripe,
  Typeform, Calendly) show how to get those exports, and its customer-research,
  ab-testing, pricing and cro skills go deeper on method.
- The thresholds behind the grades (5 and 10 interviews, 30 and 100 survey
  answers, 10 and 30 qualified actions, 3 and 10 paying customers) are cautious
  conventions, not statistical proof.
- The record is a file on the founder's disk. There are no user accounts or
  roles; who made each change is logged, and the log is tamper-evident. It holds
  what participants said, so share exports with care and honour a withdrawal
  with `VALIDATE participant redact`.
- Pre-orders and deposits have legal rules that differ by country. The skill says
  what to check; a professional confirms it. Not legal or financial advice.

## Output

`founder/validation/`: `validation.db`, `records/`, `synth/`,
`validation-report.md`, `dashboard.html`, `export/`. `/founder-plan` includes the
validation report and status in the business plan.
