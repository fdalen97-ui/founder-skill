# Real surveys: build, field, import, read

The tool builds and checks the instrument, prints a form, and imports the
answers. It does not send a survey or reach a respondent. The founder builds the
form in the survey tool they already use (Google Forms, Typeform, Tally,
SurveyMonkey...) and exports the answers as CSV.

## The instrument

```json
{"title": "How adjusters write up inspections",
 "population": "loss adjusters who wrote a report in the last month",
 "intro": "Five minutes, anonymous. We are studying how inspection reports get written.",
 "min_duration_s": 45,
 "questions": [
  {"id": "q1", "kind": "screening", "type": "single",
   "text": "Did you write an inspection report in the last month?",
   "options": ["Yes", "No"], "qualifies": ["Yes"]},
  {"id": "q2", "kind": "behavioral", "type": "single", "ordered": true,
   "text": "How many inspection reports did you write last month?",
   "options": ["1 to 5", "6 to 20", "More than 20"]},
  {"id": "q3", "kind": "behavioral", "type": "multi", "randomize": true,
   "text": "Which of these did you use for your last report?",
   "options": ["A Word template", "Dictation", "An assistant or temp", "Dedicated software", "None of these"]},
  {"id": "q4", "kind": "behavioral", "type": "number",
   "text": "In the last 3 months, how much did you spend on help writing reports? (0 if nothing)"},
  {"id": "q5", "kind": "stated", "type": "single", "ordered": true,
   "text": "How likely are you to change how you write reports in the next 6 months?",
   "options": ["Very unlikely", "Unlikely", "Likely", "Very likely"]},
  {"id": "q6", "kind": "demographic", "type": "single", "ordered": true, "required": false,
   "text": "How many years have you worked as an adjuster?",
   "options": ["Under 3", "3 to 10", "More than 10"]}]}
```

| field | meaning |
| --- | --- |
| `kind` | `screening`, `behavioral`, `stated`, `pricing`, `demographic`, `open` |
| `type` | `single`, `multi`, `number`, `text` |
| `qualifies` | on a screening question: the answers that let a respondent through |
| `randomize` | shuffle the option order per respondent (set this in the survey tool too) |
| `ordered` | the options are a scale; an ordered scale is never shuffled |
| `required` | defaults to true; a blank required answer makes the row incomplete |
| `min_duration_s` | answers faster than this are excluded as too fast |

## Writing questions

- **Screen first.** Ask what the person did, in a way that does not reveal which
  answer qualifies. Offer several activities, not a yes/no about yours.
- **Behaviour before opinion.** Past behaviour questions (`behavioral`) name a
  time window: "in the last month", "your last report". They go first.
- **Stated preferences are labelled.** Likelihood, interest and "would you"
  questions are `stated`. They are reported under their own heading and can never
  support a claim above weak. A question marked `behavioral` that asks about the
  future is refused.
- **Neutral wording.** No adjectives that carry the answer ("how useful", "how
  frustrating"). The tool refuses leading wording.
- **Balanced, shuffled options.** Unordered lists get `randomize: true`, with
  "None of these" and "Other" available. Scales are balanced and stay in order.
- **One thing per question.** No "and".
- **Demographics last, optional, and only the ones you will actually use.**

`survey create` checks all of this. Errors block creation; warnings are for you
to weigh and tell the founder about.

## Price questions

Use these to choose prices to test with a real offer. They are exploratory
methods, not proof of demand.

**Van Westendorp**: four `pricing` number questions, then map them:

```json
"van_westendorp": {"too_cheap": "p1", "cheap": "p2", "expensive": "p3", "too_expensive": "p4"}
```

- p1: At what price would this be so cheap you would doubt its quality?
- p2: At what price would it be a bargain?
- p3: At what price would it start to feel expensive, though still worth considering?
- p4: At what price would it be too expensive to consider?

**Gabor-Granger**: one `pricing` number question for the highest price the person
says they would pay, mapped with `"gabor_granger": {"question": "p5"}`. The tool
reports the share who said they would pay each price and where stated revenue
peaks. People overstate what they will pay, so read the curve's shape, not its
level.

## Fielding

```bash
python3 validate.py survey create --json survey.json
python3 validate.py survey form SV001 --out founder/validation/survey-SV001.md
```

The form lists each question with its column id. The founder builds it in their
tool, turns on option shuffling where the form says so, and sends it. Record how:
a survey sent to your own mailing list reached people who already like you, and a
paid panel reached people paid to answer. Both are fine to use and neither is the
market. Say which it was with `--via`.

Typical sizes: 30 valid answers for a first read, 100 before quoting a
percentage. `validate.py experiment plan-sample --type landing_page --baseline
0.3 --margin 0.1` gives the number for a chosen margin of error.

## Importing

Export as CSV with one column per question id, plus these if the tool provides
them: `respondent_key` (any stable anonymous id), `submitted_at`, `duration_s`.
Multi-choice answers are separated by `;`.

```bash
python3 validate.py survey import SV001 --csv export.csv --via "trade association newsletter" --from 2026-03-01 --to 2026-03-14
```

Exclusion rules, applied in this order and reported by count:

| reason | rule |
| --- | --- |
| `duplicate_respondent` | the same `respondent_key` has already answered; the first answer is kept |
| `duplicate_row` | an identical row (same answers, same key or timestamp) |
| `incomplete` | a required question is blank |
| `screened_out` | a screening answer is not among `qualifies` |
| `too_fast` | `duration_s` is below `min_duration_s` |

Excluded rows stay in the record with their reason. To exclude one by hand
(a co-founder answered, a test submission) use `survey exclude <response id>
--reason "..."`. Without a `respondent_key` column the tool cannot detect the
same person answering twice, and it tells you so.

## Reading the results

`survey show SV001` and the report give, for every question, the number of valid
answers, each option's count and share, and a 95% interval. When you present
them:

- Start with who answered: how many were received, how many are valid, how they
  were reached.
- Report past behaviour and stated preferences under separate headings.
- Never say "representative". The tool reports it as not established unless you
  have evidence the sample mirrors the population, and it has no way to check.
- Do not compare subgroups of fewer than 30. Do not quote a percentage from
  fewer than 30 answers without its interval.
- To use a result as evidence, attach the question to a claim (category E) with a
  `match`. The tool counts the matching valid answers itself.
