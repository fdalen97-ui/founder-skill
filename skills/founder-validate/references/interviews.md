# Real customer interviews: recruit, ask, file

You help the founder prepare and analyse. The founder does the recruiting and the
talking. Nothing is recorded as having happened until it has.

## Who to talk to

Write these with the founder before any outreach:

- **Recruitment criteria**: the segment's screening criteria, restated as things
  you can check ("signed off a software purchase in the last 12 months").
- **Who is excluded**: friends, family, investors, colleagues, anyone who knows
  the idea and wants to be kind.
- **Roles**: for B2B, list the user, the buyer, the budget owner and the
  procurement decision-maker separately. They are usually different people, and
  the person who likes the product is often not the one who pays. Interview each.
- **Target**: 5 people per segment for a first read, 10 before relying on it.
  Write the targets to a file, for example `{"SEG001": 10}`, and set them with
  `validate.py recruit --json targets.json`.

## The screener

Three to five questions asked before the interview, about facts and recent
behaviour. No question should reveal which answer qualifies.

```
1. Which of these have you done in the last month? (list of 6 activities; one is the target)
2. Roughly how many times?
3. Who decides which tools or services you use for it?
4. What do you use for it today?
```

Record the outcome on the participant: `screened_in` or `screened_out`.
Screened-out people stay in the record. They are part of the sample story.

## Outreach

Short, honest, no pitch. Say who you are, what you are studying, what you are
asking for and what they get. Templates to adapt:

**Cold message**

> Hi {name}, I am researching how {role}s handle {situation}. I am not selling
> anything. Could I ask you about your experience for 20 minutes this week? Happy
> to send a {incentive} as thanks.

**Invitation after a yes**

> Thank you. Here are three times: {slots}. It is a 20 to 30 minute call. With
> your permission I would like to record it so I can listen instead of taking
> notes. The recording stays with me, and anything I quote will be anonymous. You
> can ask me to delete it at any time.

**Incentive**: a small gift card or a donation, the same for everyone, promised
up front and paid whether or not they like the idea. Never pay for a positive
answer and never offer the product itself as the incentive in a problem
interview.

## Consent

Before storing anything a person said, record what they agreed to:

```json
{"segment_id": "SEG001", "role": "user", "recruited_via": "trade association forum",
 "status": "scheduled", "consent": "recorded", "consent_scope": "recording, storage, anonymous quotes",
 "characteristics": "12 years in the trade, works alone"}
```

`label` is optional. Keep names, emails and phone numbers out of the record; use
your own contact list for those. If someone withdraws, run
`validate.py participant redact PT004 --reason "withdrew consent"`.

## The five guides

Write the guide as a markdown list of questions, then run
`validate.py guide lint guide.md --type <type>` and fix every flag. At least half
the questions in a problem interview should be about something that already
happened.

### 1. Problem discovery (`problem_discovery`)

No product. No pitch. You are finding out whether the problem exists for this
person and what they already do about it.

- When did you last {situation}? Walk me through what happened.
- What did you do next?
- How long did it take? What did it cost you?
- How often does that come up?
- What have you tried to make it easier? What happened?
- Have you paid for anything to deal with it? What, and how much?
- What happens if you just leave it?
- What else did you consider?
- Who else is involved when this happens?

Never ask "Would you use an app that solves this?" The answer is always yes and
means nothing.

### 2. Solution testing (`solution_testing`)

Only with people who have the problem. Show a mock-up or do the service by hand.
Watch more than you ask.

- (Give them the task.) Please do {task} and think out loud.
- What did you expect to happen there?
- What does this replace in how you work today?
- What stops you using this next week?
- Who else has to agree before you can use it?

### 3. Pricing (`pricing`)

Anchor on what they already spend, not on what they imagine paying.

- What do you spend today on {the alternative}? Per month?
- When did you last pay for a tool or service in this area? What did it cost?
- What made that one worth the money, or not?
- (State the real price.) What do you compare that with?
- What should be included at that price?

If you ask what they would pay, file the answer as a `statement`, not as `spend`.
Stated willingness to pay is not demand.

### 4. Purchasing decisions (`purchasing`)

- The last time your company bought something like this, how did it go, step by
  step?
- Who first raised it? Who signed? Who could have said no?
- Whose budget did it come from? Was the money already set aside?
- How long from first conversation to signature?
- What nearly stopped it?

### 5. Post-purchase (`post_purchase`)

For pilot and concierge customers.

- What were you trying to get done when you signed up?
- What did you do the first week?
- What do you still do the old way? Why?
- Have you recommended it to anyone? Who? What did you say?
- What do you do on the days it is not available?

## Filing an interview

The tool does not transcribe audio. Ask the founder for the transcript from the
tool they recorded with (`.txt`, `.md`, `.vtt` or `.srt`), or for their own notes.

```json
{"participant_id": "PT003", "guide_type": "problem_discovery", "conducted_on": "2026-03-14",
 "interviewer": "founder", "medium": "video call", "record_kind": "transcript", "record_path": "calls/pt003.vtt"}
```

`record_kind` is `transcript` (the customer's words) or `notes` (the
interviewer's words). Notes can never yield a verbatim quote.

Then one extract per finding:

```json
{"interview_id": "IV003", "kind": "spend", "verbatim": true, "theme": "typing cost",
 "text": "I paid a temp four hundred dollars last month to type them up", "amount": 400, "currency": "USD"}
```

| kind | what it is | counts as past behaviour |
| --- | --- | --- |
| `behavior` | something they did | yes |
| `spend` | money or time they actually spent | yes |
| `statement` | an opinion, a wish, a stated intention | no |
| `unmet_need` | something they want and cannot get | no |
| `objection` | a reason against | no |
| `trigger` | what made them act or look for a solution | no |
| `alternative` | what they use instead | no |
| `contradiction` | where what they said and what they did disagree, or where they disagree with others | no |

Rules for extracts:

- `verbatim: true` only for exact words. The tool checks them against the
  transcript and refuses anything else. Do not tidy a quote to make it stronger.
  Lines labelled as the interviewer (`Interviewer:`, `Intervjuer:`, `Q:`,
  `Moderator:`) are left out of the check, so label your own lines in the
  transcript: an unlabelled question of yours could otherwise pass as a quote.
- Everything else is a summary. Set `author` to `ai` when you wrote it and
  `founder` when they did. Reports label it as a summary, never as a quote.
- Tag a `theme` in the customer's vocabulary, the same word for the same thing
  across interviews, so people can be counted per theme.
- File the things that hurt: the person who shrugged, the one who already solved
  it for free. Use `objection` and `contradiction`. They are evidence too.

## Reading the analysis

The interview analysis counts distinct people per theme, splits them by segment
and role, separates quotes from summaries, lists contradictions and marks themes
only one person raised as outliers. When you present it:

- Lead with who was asked: how many, which segment, how they were found.
- "4 of 6 solo adjusters" and never "most customers".
- Six people from one forum describe those six people. Say what kind of person is
  missing from the sample.
