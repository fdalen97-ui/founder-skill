# Behavioural experiments: design, run, import, read

Interviews and surveys record what people say. Experiments record what they do.
The tool holds the design, the counts and the payments. It does not build a
page, buy traffic or take money: the founder runs the test with their own tools
and imports what happened.

## The order of events

1. **Design** the test and write down the decision rule.
2. **Register** it (`experiment register`). The design is dated and audited
   before any data exists.
3. **Launch** (`experiment launch`). From here the design is locked. A change is
   an amendment: `experiment amend X001 --change "..." --reason "..."`.
4. **Import** the counts and payments, each with where the number came from.
5. **Read** against the rule you wrote (`experiment read`).
6. **Close** with a written conclusion (`experiment complete`, or `abandon`),
   then attach the result to a claim as evidence, for or against.

Never start with step 4. A result with no rule written beforehand can be made to
mean anything.

## The design

```json
{"type": "landing_page", "title": "Demo page, newsletter traffic",
 "hypothesis_id": "H004", "segment_id": "SEG001", "concept_id": "K001",
 "design": {
  "learn": "Whether qualified adjusters ask for a demo when they see the offer and the price",
  "population": "Loss adjusters reached through the trade association newsletter",
  "method": "One page: what it is, the price, one button. Form asks how many reports they write a month.",
  "qualification": "Answered 6 or more reports a month on the form, or arrived from the association newsletter link",
  "primary_metric": {"event": "demo_request", "denominator": "visit"},
  "secondary_metrics": ["cta_click", "signup"],
  "stopping_rule": {"min_denominator_per_variant": 250, "max_days": 21},
  "decision_rule": {"success_at": 0.05, "fail_below": 0.02},
  "outcomes": {
    "success": "Qualified demand at this price. Next: offer a paid pilot to the people who asked for a demo.",
    "failure": "Qualified adjusters saw it and did not act. Rework the offer before any more traffic.",
    "inconclusive": "Between the lines. Run it once more on a second channel before deciding."},
  "cost_estimate": 300, "days_estimate": 14}}
```

Every field above is required. The tool refuses a design without them.

- `primary_metric`: ONE event that decides the test, and its denominator.
- `qualification`: how you know a visitor or prospect is in the target segment.
  Decide it before launch. Traffic you cannot qualify is recorded as unknown.
- `stopping_rule`: how many qualified observations per variant, and the latest
  day you will stop. `experiment plan-sample` computes the number.
- `decision_rule`: for one version, the rate that counts as success and the rate
  below which it failed. For `ab_test` and `price_test`, `min_effect` (the
  smallest absolute difference worth acting on) and optionally `alpha` (default
  0.05), plus `variants` with the control first.
- `outcomes`: what you will conclude and do in each case, written now.
- `offer_terms` (required for `preorder`, `price_test`, `concierge`, `pilot`):
  exactly what the customer is told about price, delivery, refunds and charging.

## Planning the sample

```bash
python3 validate.py experiment plan-sample --type landing_page --baseline 0.05 --margin 0.03
python3 validate.py experiment plan-sample --type ab_test --baseline 0.05 --min-effect 0.02
```

The second usually returns a number in the thousands per version. If the founder
cannot reach that many qualified people, an A/B test cannot answer the question:
say so, and test one version against a pre-set line instead, or test a bigger
difference.

## Importing what happened

Counts come from the founder's own systems: an analytics export, a form tool, a
payment dashboard, a spreadsheet of sales calls. CSV columns:

```
occurred_on,event,count,qualified,variant,traffic_source,audience,cost,price_point
2026-03-04,visit,180,yes,,association newsletter,members,300,
2026-03-04,demo_request,14,yes,,association newsletter,members,0,
2026-03-05,visit,900,,,social post,unknown,0,
```

`qualified` is `yes`, `no` or blank (unknown). Only `yes` rows enter a rate.
Unqualified and unknown traffic is shown beside the result, never inside it: a
thousand curious visitors from a viral post are not evidence of demand from the
target customer. If none of the traffic is qualified, the reading is
"unreadable", not zero.

`experiment record X001 --json events.json` takes the same fields as JSON, with
`origin_record` naming the export or log each count came from. Mistakes are
voided with a reason (`void event <id> --reason "..."`), never edited.

## Money

A transaction is recorded only when money moved or a contract was signed, the
customer explicitly agreed, and there is a receipt, invoice or contract id.

```json
{"experiment_id": "X002", "payer_ref": "cust-0007", "kind": "deposit", "amount": 49, "currency": "USD",
 "price_point": 49, "occurred_on": "2026-03-10", "reference": "stripe ch_...", "authorized": true}
```

`kind`: `deposit`, `payment`, `repeat_payment`, `contract_signed`, `refund`,
`cancellation`. Refunds and cancellations subtract; a customer whose net is zero
is not a paying customer. `payer_ref` is any stable anonymous id. A reservation
with no money, a letter of intent or a "yes, send me the invoice" is a behaviour
event, not a transaction.

## The six experiments

### 1. Landing page test (`landing_page`)

A page describing the product with one real action. Events to record: `visit`,
`cta_click`, `signup`, `demo_request`, `qualified_lead`, each with traffic source,
audience and cost. Reads as qualified conversion with an interval, cost per
conversion and a breakdown by source. Describe the product as it is: no claims it
cannot keep, and say plainly if it is not available yet.

### 2. Price test (`price_test`)

The same offer at two or more prices to comparable qualified prospects, assigned
at random. `variants` and `price_points` are required. Use real offers: separate
pricing pages, quotes, checkout. Everyone pays the price they were shown. Reads
as acceptance per price with intervals, the difference, and arc elasticity when
both arms have enough conversions. Van Westendorp and Gabor-Granger (see the
survey guide) help choose which prices to test. They do not replace this.

### 3. Pre-orders and deposits (`preorder`)

Events for the steps before money (`offer_seen`, `reservation`), transactions for
the money (`deposit`, `payment`, later `cancellation`, `refund`,
`repeat_payment`). The offer must be transparent: what the customer gets, when,
what happens if it is never built, how to get the money back. Rules on taking
payment for goods not yet delivered differ by country and by payment provider;
tell the founder to check them before taking a single deposit. Never charge
without explicit authorisation.

### 4. Concierge MVP (`concierge`)

Sell the outcome and deliver it by hand before building anything. Events:
`lead`, `customer_started`, `delivery` (with `cost` for money spent; note hours
in the `audience` or origin record), `repeat_use`. Transactions for what they
pay. This is the best source for the economics question: the measured cost and
time to serve one customer, and whether they come back.

### 5. B2B pilot (`pilot`)

Events along the funnel: `qualified_prospect`, `meeting`, `demo`,
`pilot_agreement`, `pilot_completed`, `paid_conversion`. Transactions:
`contract_signed` with the contract value, then `payment`. Record dates so the
sales cycle can be read. A free pilot is behaviour evidence; only a paid one is
payment evidence. Write the success criteria and the conversion price into the
pilot agreement before it starts.

### 6. A/B test (`ab_test`)

Two versions of one thing: value proposition, headline, price presentation,
feature, offer, onboarding step or call to action. Change one thing. The tool:

- labels any reading before the planned sample as interim, counts it as a look,
  and declares no winner;
- at the planned sample, reports the difference in points, its interval, the
  relative lift and a p-value;
- declares a winner only when the difference is statistically detectable AND at
  least the minimum effect set before launch;
- says "no reliable difference" when that is the case, which is not the same as
  proving the versions are equal.

## Reading a result to the founder

- Give the count and the interval, not just the percentage: "20 of 250 qualified
  visitors, somewhere between 5% and 12%".
- Say what was left out and why.
- Read the outcome against the line set before launch, in the words written then.
- A failed test is a result. Close it with its conclusion and file it as
  contradicting evidence on the claim it tested.
