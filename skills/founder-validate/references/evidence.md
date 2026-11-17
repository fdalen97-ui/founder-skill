# The evidence record: categories, shapes, grading

Everything `validate.py` accepts, and how it turns records into grades.

## Hypotheses: what to cover

| area | must be true |
| --- | --- |
| market | The market is large enough. Demand is growing. There are underserved segments. Existing alternatives are not good enough. |
| problem | The problem exists. It happens often. It is costly or frustrating. People do something about it today. Doing nothing has a consequence. |
| product | The solution solves the problem. It is clearly better than the alternatives. Nothing blocks adoption. The essential parts are known. |
| commercial | Someone makes the buying decision. Someone pays. A budget exists. They will pay the planned price. The buying process is short enough. |
| distribution | Customers can be reached. A customer can be acquired for less than they are worth. At least one channel works commercially. |

```json
{"area": "problem", "statement": "Independent adjusters lose more than two hours writing each report",
 "origin": "ai", "impact": 5, "uncertainty": 4, "test_cost": 1, "test_time": 2,
 "if_false": "There is no pain to pay for; the product is a convenience at best.",
 "segment_id": "SEG001"}
```

Scores are 1 to 5. Priority = impact x uncertainty / the average of test_cost and
test_time. A hypothesis is "answered" only when real evidence makes it at least
moderately supported or contradicted. Synthetic exploration never answers one.

## Segments and concepts

```json
{"name": "Solo adjuster", "definition": "Independent loss adjusters working alone",
 "criteria": "writes 20 or more inspection reports a month", "basis": "assumption"}
```

```json
{"name": "Report drafting, per seat", "description": "...", "price_point": 49, "currency": "USD"}
```

A segment with `basis: "evidence"` needs a `basis_note` naming the evidence. Do
not write market statistics you do not have a source for.

## Claims and evidence

A claim is one statement about the business. Evidence is attached for and
against it.

```json
{"description": "Adjusters already pay to get reports typed up", "dimension": "problem",
 "hypothesis_id": "H001", "segment_id": "SEG001",
 "implications": "The budget exists; the comparison price is what they pay a temp.",
 "next_experiment": "Ask 5 more adjusters what they paid last month.",
 "limitations": "All participants came from one trade association."}
```

`dimension` is one of `problem`, `solution`, `demand`, `behavior`, `payment`,
`segment`, `economics`.

```json
{"claim_id": "C001", "stance": "supports", "category": "D",
 "ref": {"extracts": [3, 7, 12]}, "summary": "Three adjusters paid a temp or an assistant last month",
 "limitations": "Self-reported amounts."}
```

| category | what it is | `ref` must contain | real units counted |
| --- | --- | --- | --- |
| A | assumption or AI-drafted hypothesis | nothing | none |
| B | synthetic customer response | `{"run": "R001"}` | none |
| C | external research | `{"sources": ["SRC001"]}` | distinct sources (weak at most) |
| D | customer interview | `{"extracts": [ids]}` | distinct interviewed people |
| E | survey | `{"survey": "SV001", "question": "q2", "match": {"in": ["Weekly"]}}` | valid matching answers |
| F | observed behaviour | `{"experiment": "X001", "event": "demo_request", "denominator": "visit"}` | qualified events, one pool per experiment |
| G | purchase or commitment | `{"experiment": "X001"}` or `{"transactions": ["T001"]}` | distinct net payers |

Behaviour evidence follows the experiment's own result. Events from an
experiment that failed its pre-set line cannot be filed as support, and an
experiment counts against a claim (by the qualified people who saw the offer and
did not act) only when it failed. The denominator event, such as `visit`, is
never an action. Screening answers do not count as past behaviour: every valid
respondent passed the screener.

`match` accepts `in` (a list of options), `gte`, `lte` and `eq` for numbers. Add
`"among": {"question": "q1", "in": ["Yes"]}` to count within a subgroup. The
category must match the kind of record: the database rejects, for example, a
synthetic run filed as an interview. Category, reference, stance and summary can
never be edited afterwards. Use `retract` and add a new item.

Research sources (category C) need a real link or a file you hold:

```json
{"kind": "competitor_price", "title": "Competitor A pricing page", "url": "https://...",
 "publisher": "Competitor A", "accessed_on": "2026-03-14", "price": 79, "currency": "USD",
 "price_includes": "one user, 50 reports a month", "excerpt": "..."}
```

`kind`: `report`, `statistic`, `competitor_price`, `review`, `forum`, `article`, `other`.

## The synthetic lab

Lab profile (`--customer`):

```json
{"business": "...", "target": "independent loss adjusters who write 20+ reports a month",
 "situation": "Writing up an inspection report after visiting a damaged property.",
 "segments": [{"name": "Solo adjuster", "share": 0.6, "income": [50000, 90000]}],
 "alternatives": ["a Word template", "dictating to an assistant", "nothing"],
 "occupations": ["loss adjuster"], "behaviours": [{"name": "Reads every review", "how": "..."}],
 "habits": ["on the road four days a week"], "purchase_contexts": ["end of month, reports overdue"],
 "experience_levels": ["15 years in the trade"], "age": [28, 60],
 "evidence_basis": {"segments": "assumption", "alternatives": "evidence: 6 interviews"}}
```

`situation` describes the moment being studied and must not mention the product.
`evidence_basis` says which fields rest on real data; anything unlisted is
recorded as an assumption. Segment shares are dealing quotas, never market
statistics. `archetype_mix` (optional) reweights the nine dispositions:
`enthusiast`, `skeptic`, `price_sensitive`, `satisfied`, `no_problem`,
`high_power`, `change_averse`, `influencer`, `tried_before`. Enthusiasts are
capped at 20%; skeptics, the satisfied and people without the problem together
must be at least 30%; at least six dispositions must be present.

Arms (`--arms`): one per alternative being compared. Keep everything identical
except the thing under test.

```json
[{"id": "A", "offer": "A service that turns an inspection recording into a draft report you review and approve.",
  "price": 49, "scenario": "You have three reports due this week and see this in a trade newsletter."},
 {"id": "B", "offer": "...the same words...", "price": 99, "scenario": "...the same words..."}]
```

The run record freezes the model, prompt version, seed, number of profiles,
repeats, the situation and your `--assumptions`. A hundred answers from one model
are a hundred correlated outputs of that model, not a hundred observations. To
check sensitivity, repeat the run (`--repeats`), change the seed, or run it again
on a different model and compare the themes, not the counts.

## Predictions and calibration

```json
{"source": "founder", "prediction_type": "demo_request_rate", "measured_what": "qualified visitors requesting a demo",
 "predicted": 0.10, "segment_id": "SEG001", "price_point": 49, "methodology": "gut feel before launch"}
```

```json
{"prediction_id": "P001", "experiment_id": "X001", "event": "demo_request", "denominator": "visit",
 "measured_what": "qualified visitors requesting a demo", "comparable": false,
 "comparable_note": "the prediction was a simulated stance; the result is an action"}
```

A prediction is frozen when recorded and cannot be added after the experiment has
finished. `comparable` is your honest call on whether the two numbers measure the
same thing for the same audience at the same price. Only comparable pairs feed
calibration, and no figure is computed below five of them per source, model and
prediction type.

## How grades are computed

| | weak | moderate | strong |
| --- | --- | --- | --- |
| C: independent sources | 1 | never | never |
| D: interviewed people | 1 | 5 describing past behaviour or spend | 10 |
| E: valid survey answers | 1 | 30 to a past-behaviour question | 100 |
| F: qualified observed actions | 1 | 10 | 30 |
| G: paying customers, net | 1 | 3 | 10 |

Which categories can answer which question, and how far:

| question | C | D | E | F | G |
| --- | --- | --- | --- | --- | --- |
| problem | weak | strong | strong | strong | strong |
| solution | no | moderate | weak | strong | strong |
| demand | weak | weak | weak | strong | strong |
| behavior | no | no | no | strong | strong |
| payment | no | no | no | no | strong |
| segment | weak | moderate | strong | strong | strong |
| economics | weak | weak | no | moderate | strong |

Opinions in interviews and answers to `stated` or `pricing` survey questions
never count above weak, whatever the number. Evidence against is graded the same
way: if it reaches moderate and at least matches the support, the question is
Contradicted; weaker evidence against holds the grade one step down and marks it
contested.

The recommendation: **No-Go** when problem, demand, payment or economics is
contradicted. **Go** when all seven are at least moderate. **Conditional Go**
when the problem is at least moderate and there is some real demand signal, with
the open questions listed as conditions. Otherwise **No recommendation yet**.

These numbers are conventions set to be cautious for an early-stage founder.
They are not statistical thresholds and the report says so.

## Governance

The database enforces these; do not look for a way around them.

- Evidence, claims, synthetic runs and responses, predictions, behaviour events,
  transactions, survey responses and interview extracts cannot be deleted.
- Corrections are made by retracting, voiding or excluding with a reason. The
  original stays visible.
- An experiment's design locks at launch. Changes are amendments on the record.
- Every write is logged with who made it, in a hash-chained table.
  `validate.py audit` shows when audit entries were edited or removed.
- What this protects against is self-deception and casual edits. Someone with the
  file and the intent to rewrite it wholesale can still do so; it is not a
  notarised ledger.
- Store the least personal data that does the job: a participant label is
  optional, and contact details stay out of the record entirely.
- `participant redact` removes a person's words and stored transcript and stops
  counting them, when they withdraw.
