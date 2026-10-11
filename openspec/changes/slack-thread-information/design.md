## Context

The first two Slack-inbound changes built the path in:
- `argus_web` ingests a reply as `PersonWrote`, claiming its reference in the
  same transaction to drop a duplicate delivery;
- `agent_intent` classifies it (`MessageUnderstood`) and, for an ending the
  incident accepts, offers it (`ResolutionOffered`, `WithdrawalOffered`);
- the walk's wait (`argus_incidents.waiting`) holds the next step until each
  message is answered, and publishes `OfferExpired` at 5 minutes;
- a press (`argus_web.chat._confirm`) finds its offer and ends the incident.

`information` is classified and narrated, and nothing else happens.

Two things decide on events today: the wait reads `PersonWrote`,
`MessageUnderstood`, both offers and `OfferExpired`; the press reads the
offers. The `incident-event-stream` capability forbids exactly that ("no
decision, verdict or action may depend on a published event"), and the
`events.py` docstring says the same. This change would add a third: the
Investigator deciding on a lead it read off the log.

What the agents receive today:
- the **Investigator** is a tool loop. Its opening message is built once from
  the alert and the walk's state; `still_wanted()` is asked before every turn;
  `_ONE_TURN_LEFT` already rides on a tool result;
- **Mitigation** is deterministic: the proposal is derived from the chosen
  hypothesis's failure mode. Candidates are tried in the model's rank order,
  possibly reordered by memory. Confidence gates nothing;
- **Code-Fix** is a tool loop shaped like the Investigator's;
- the **Postmortem** makes at most two calls over evidence gathered from the
  database. The timeline already carries the person's words, unlabelled.

## Goals / Non-Goals

**Goals:**
- A lead written in the thread reaches every model-backed agent that runs
  after it is understood, and the two tool loops mid-conversation.
- The Investigator weighs every lead it is shown, and the person is told how.
- Nothing decides on an event.

**Non-Goals:**
- `question`. That is the next change.
- Reopening a finished investigation for a late lead (D7).
- Mitigation reading leads. It has no model, and a lead reaches it through the
  hypothesis it shaped.
- Anything in the demo app.

## Decisions

### D1. The conversation is a table in the incident record

Migration `001` gains `thread_message`, one row per message written in an
incident's thread, keyed by the message's reference (`source`, `kind`,
`value`):

| Column | Written by | When |
| --- | --- | --- |
| `incident_id`, `person_id`, `text`, `written_at` | ingestion | delivered |
| `meaning` | the intent agent | classified |
| `person_name` | the intent agent | offered, or understood as a lead |
| `offered_ending` | the intent agent | offered |
| `offer_expired` | the wait | 5 minutes unanswered |
| `standing`, `standing_reason` | the walk | the Investigator weighed it |

A column is added by the test that needs it, so the table may end smaller than
this. A new repository, `argus_incidents.repository.conversation`, holds the
reads and writes. `get()` takes the reference; relational reads are named for
what they look up by.

The row is the work and the event is the account, as everywhere else: the row
is written, then the event is published, and a publish that fails costs the
timeline a line and decides nothing. Ingestion stays the one exception it is
today - the row and `PersonWrote` are recorded in one transaction - because a
message kept and never told of is a hole in the one record of what a person
said that a reader of the timeline has.

The row replaces the message's reference claim. Nothing read that claim: it
was only how a repeated delivery was refused, and the row's key refuses it
now, in the same write as the fact. `references.claim` goes with it.

*Alternative:* read the event log and reword the rule to exempt conversation
events. It is less code, and it leaves a requirement that says one thing and an
exception that says another. A person's words are a fact about the incident
that came from outside, and facts live in the record.

### D2. Everything that decides reads the table

- **The wait** asks the repository which messages are unanswered. The rule
  does not change: an unclassified message is unanswered; a classified one is
  answered unless it asks for an ending the current status accepts, has an
  offer, and the offer has neither been pressed nor expired. Expiry sets
  `offer_expired`, then publishes `OfferExpired`.
- **The intent agent** finds the messages it has not classified on the table,
  oldest first, rather than following the log under a cursor of its own. The
  semantics do not change: messages are understood in order, and one that
  fails holds up those behind it until the next look. Its `event_cursor` row
  goes unused, and the reader is retired.
- **The press** finds the offer on the row.
- **The agents** read leads from it (D3).

After this, `events.py`'s docstring is true without amendment, and a test in
the wait's suite proves it: the same rows with no events recorded give the same
answer.

### D3. A lead, and how an agent gets it

A **lead** is a message understood as `information`: a `ThreadMessage` (the
kernel's one shape for a message, D1) whose `weighing` - a `Standing` and its
reason - is set once an investigation has weighed it. No `Lead` type of its own:
it would be the same fields under a second name. Where a model names a lead
back - the Investigator weighing it, the postmortem saying what it changed -
each is labelled `L1`, `L2`, … in the order written, by `labelled` in
`argus_core.models`, so both number alike. The label is stable within a walk.
Code-Fix names no lead back, so its leads carry none.

The walk hands each agent one seam, `leads: Leads` (`Callable[[],
list[ThreadMessage]]`, defaulting to `no_leads`), that answers every lead the
incident has, each with its current weighing. It is bound in `graph.py` beside
`still_wanted`, over `conversation.get_leads_by_incident`.

The Investigator and Code-Fix ask it before each turn, and work out for
themselves which leads they have not yet shown. Those asked before the first
turn go in the opening message; later ones ride on the next tool result, in a
section of their own after the result, as `_ONE_TURN_LEFT` does. A lead posted mid-investigation therefore reaches the
model on the turn after it is classified, and never interrupts a tool call.

*Alternative:* leads only at the start of each step. A lead posted during the
investigation would reach nobody, unless the candidate that investigation chose
is refuted. That is the case scenario 7 describes.

### D4. The Investigator weighs every lead it is shown

`weigh_lead(lead, standing, reason)` is a new answer tool beside
`final_answer`. `standing` is one of three values (`Standing` in the kernel):
- **supported**: something the Investigator read agrees with it;
- **refuted**: something it read contradicts it;
- **unverified**: neither.

The `weigh_lead` description and the leads section say what each standing
allows - not the brief, so a walk with no leads sends today's brief:
- a refuted lead is not acted on;
- a supported lead is evidence like any other, cited in a hypothesis's
  `supporting_evidence`;
- an unverified lead may still be a candidate, at the confidence the model
  gives it, ranked among the rest. It passes the tier gate like any candidate,
  so the autonomy rules are untouched.

`final_answer` is refused, through its own tool result, while a lead shown is
unweighed, as an unreadable answer is refused today - but only while the budget
leaves a turn to weigh it in. On the last turn a refusal can lead nowhere but an
undetermined ending, so the answer is taken and the lead comes back unweighed.
The standings come back from every ending, not only an answer: a weighing is a
reading of the evidence, and outlives whether a cause was named. A lead weighed twice keeps
the later standing. A walk that returns to the Investigator after a refutation
shows each lead with its earlier standing and asks for it again.

The tool is offered from the turn the first lead is shown, not before, so a
walk with no leads sends exactly the requests it sends today.

*Alternative:* a `leads` field on `final_answer`. That puts the weighing at the
end, after the model has already ranked, and changes the answer's schema for
every walk. A separate call lets the weighing happen as soon as the evidence
for it is read.

### D5. The walk records the standing, and the person is told

The Investigator returns the standings with its findings. The walk writes each
one to its row, then publishes `LeadWeighed(message, standing, reason)`.
Narration gives it a line: "Weighed the lead from the thread as supported -
{reason}". The relay follows it and posts it in the thread.

### D6. Code-Fix gets leads with their standings

Its opening message carries each lead with the Investigator's standing. A lead
the Investigator never saw is labelled unweighed. Code-Fix gives no standing:
weighing a lead against evidence is the Investigator's job, and Code-Fix reads
code, not telemetry. Leads arriving mid-loop ride on the next tool result, as
in D3, or on a plain message after a turn that asked for nothing.

Each standing was given before anything was tried, and a lower candidate can be
the one an action then confirms - so a refuted lead can name the confirmed
cause. Nothing links a lead to a candidate, so the standing is not overridden;
Code-Fix is told the finding outranks any weighing, and the Postmortem that the
actions are the later word.

### D7. A late lead does not reopen the investigation

A lead understood after the Investigator has answered reaches Code-Fix and the
Postmortem, and is shown to the Investigator if the walk returns to it after a
refuted mitigation. Reopening a finished investigation is a walk-shape change
of its own and is not needed for a lead to be used.

### D8. The postmortem says what people told Argus

Evidence gains the incident's leads, read from the table. The prompt gives them
a labelled section. `PostmortemDocument` gains `leads`: for each one, the
record's facts (who, the words, the standing and its reason) and the model's
one sentence on whether it changed what was done.

`submit_postmortem` gains `lead_effects`, one `{lead, effect}` per lead,
required, and the check refuses a submission that leaves a lead out, as it
refuses a missing field. The field is offered only where there are leads, as
`weigh_lead` is (D4): an incident nobody wrote about sends the tool it always
did. The document is copied from the record, so a lead weighed again after it
is written does not rewrite it.

The postmortem page shows each lead with its standing and what it changed.

### D9. Fixture and tests

Scenario 7 is staged on the demo app's existing `competing-flag-changes`:
two flags move in the same minute and the evidence supports both readings. The
demo app's own suite describes it as the scenario that makes Argus revert the
decoy and put it back. It is the scenario both e2e cases below are recorded on.

Whether a lead *changes* what Argus does is a property of the real model, not
of the pipeline, so it is measured where the model is: an eval pair in
`tests/eval/test_investigator_eval.py` (the user writes it), the same scenario
with and without the lead, scored on which flag is ranked first. The e2e cases
prove the pipeline carries the lead to a weighing and reports it, and assert
nothing about which standing it is given - that is the model's judgement, and
a replay asserting it holds a recording to it.

Two e2e cases (the user writes them), each with its own recording:
- **Lead before the walk.** The thread gets "it's {the real flag}" before the
  walk starts. The lead is weighed, and the postmortem reports it with the
  standing it was given. Nothing in Argus stands between intake and the
  Investigator's opening, so the case suspends the worker before firing the
  alert and resumes it once the lead is classified: the thread, the ingestion
  and the intent agent all run without it, and the opening is built with the
  lead already there. The stack hands the suite the worker's pid; the case
  suspends the process tree (on Windows a venv's `python.exe` is a launcher
  whose child is the interpreter), and its teardown resumes it whatever the
  verdict.
- **Lead mid-investigation.** The double's hold seam (`anthropic-test-double`)
  makes it deterministic: the case holds the walk's first call, so the opening
  has gone out without the lead; it posts the lead, waits for it to be
  classified, then seeds the walk and releases. The lead reaches the model with
  the first turn's results, and the same assertions hold. The
  recording is driven the same way, with nothing seeded. The first call rather
  than a later one, because a held call's request is already written: a lead
  posted while the second call waits misses it, and reaches no investigation
  that answers on its second turn.

Both assert relations between things Argus holds (the lead's weighing on its
row against the one the postmortem reports), never a fixture number.

The between-turns mechanics (D3) are also covered in each loop's own suite,
with the seam injected.

## Risks / Trade-offs

- **The real model may follow a lead too readily.** Mitigation: the brief
  defines the three standings, and an unverified lead is ranked at the model's
  own confidence. An eval case for a wrong lead (refuted) is the next coverage
  to add.
- **The real model may not follow a right lead at all.** Both captures on
  `competing-flag-changes` refuted "it's legacy-checkout-fallback": the shop
  logs a ZeroDivisionError on the monthly-spend path the minute that flag goes
  on, and nothing it logs ties the fallback to that path. So the scenario's
  evidence supported one reading, not both. The shop now logs, for this
  scenario alone, which renderer served the account pages - all the failing
  traffic on the path the fallback had kept it off - and the eval pair states
  the same evidence. Whether that is enough for a lead to move the model is what
  the pair's pooled rates will say; both captures predate it.
- **A weighing outlives the verdict that answers it.** In both captures the
  refuted lead's flag is what confirmed, and the lead stays refuted on its row:
  nothing re-weighs a lead after the investigation that weighed it, unless a
  later round re-investigates. Code-Fix and the Postmortem are told the
  standing predates the actions (D6), so neither builds on it as the last word.
- **Record mode and the hold.** The mid-investigation recording relies on the
  hold catching the same call while recording as in replay. It does because the
  hold catches the next call to arrive rather than the next one with nothing
  queued: the queue is empty on every call of a recording and full from the
  start of a replay.
- **One table now carries the whole conversation.** Moving the wait and the
  press is a refactor of code that just landed. The wait's suite and the
  resolution and withdrawal e2e cases cover it before anything new is added.

## Open Questions

None.
