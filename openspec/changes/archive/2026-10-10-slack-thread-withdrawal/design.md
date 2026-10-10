## Context

`slack-thread-resolution` built the whole inbound path:
- `argus_web` ingests a person's reply as `PersonWrote`;
- `agent_intent` classifies it and publishes `MessageUnderstood`, and on
  `resolve` publishes `ResolutionOffered`;
- the relay posts the offer with one button and records the post as a
  `chat-offer` reference;
- a press reaches `argus_web.chat._resolve`, which checks the offer, the
  presser and the expiry, then calls `resolve_incident`;
- the walk waits (`argus_incidents.waiting`) until each message is answered or
  5 minutes have passed, then publishes `OfferExpired`;
- the relay retires every offer on an ending that no longer accepts a
  resolution, or on an expiry.

Withdrawal already exists as a mark-only operation, `withdraw_incident(id,
Report, ...)`. It is refused on a terminal incident. The walk reads the mark
back at every boundary and undoes its own changes. `fixing`, the status
Code-Fix runs under, is not terminal, so a withdrawal is accepted for as long
as Argus is still working.

The one new difficulty is that a withdrawal can stop being possible while its
offer stands, and a resolution cannot. A person who writes "stop" while
Code-Fix runs gets an offer. Code-Fix then finishes with the incident
`mitigated`, which is terminal, so the press can no longer do anything. The
walk still has steps to take (remembering, the postmortem), and without a
change it would wait 5 minutes on a button nobody can use.

## Goals / Non-Goals

**Goals:**
- A person who asks Argus to stand down in the thread, and confirms, withdraws
  the incident, credited to them through Slack with their words.
- No walk waits on an offer that can no longer be confirmed, and no such offer
  keeps its button.

**Non-Goals:**
- A reply to a request to stand down on an ended incident. As for a
  resolution, no offer is made and nothing is said: Argus has already stopped.
- `question` and `information`. Those are the next two changes.
- Any change to how a withdrawal unwinds.

## Decisions

### D1. `WithdrawalOffered`, a sibling of `ResolutionOffered`

The event has the same fields as `ResolutionOffered`: `message`, `person_id`,
`person_name` and `said`. It is a separate event rather than one generalised
`EndingOffered(ending)`, because each one is narrated, labelled and confirmed
differently, and a `match` on two classes reads better than a `match` on a
field. Code that treats both the same, namely the press lookup and the wait,
names the union once: `type Offered = ResolutionOffered | WithdrawalOffered`
in `argus_core.events`.

*Alternative:* one event carrying an `IncidentStatus`. That would rename every
`ResolutionOffered` in the suites, which the user applies by hand, for no
behaviour gained.

### D2. `IncidentStatus.accepts_withdrawal()`

This is `not is_terminal()`, the rule `incidents.withdraw` already guards
with, now named on the status as `accepts_resolution` is, so the store, the
intent agent and the wait share one copy. An already-withdrawn incident gets
no offer: the write accepts it idempotently, but offering it would be asking
someone to confirm what has already happened.

### D3. The intent agent offers

`understand` takes `status_of: Callable[[str], IncidentStatus | None]` in
place of `accepts_resolution`, and asks the status the question for each
meaning. On `withdraw`, where the status accepts a withdrawal, it names the
person and publishes `WithdrawalOffered`. Otherwise it does nothing more.

### D4. One confirm button

The action id `resolve-incident` becomes `confirm-offer`. The adapter accepts
only that id, and `Pressed` is unchanged. The press carries the person's
message, and the offer found by that message says what is being confirmed, so
the adapter does not need to know any endings.

The Communicator sets the label from the line it is saying: "Mark resolved"
or "Stand Argus down". `NarrationLine.asks_to_confirm` is set for both offer
events, and a new `NarrationLine.offers_to_end_as` (`resolved`, `withdrawn`
or `None`) says which, so the relay reads a meaning off the line, as it does
`leaves_nothing_to_resolve`, rather than matching on an event's `kind`.

*Alternative:* two action ids. That puts the endings in the adapter, and a
mismatch between the id and the offer becomes one more case to handle.

### D5. The press confirms whichever offer it answers

`ChatRecord.offer_about` returns `Offered | None`. `_resolve` becomes
`_confirm`, which runs the existing checks (no offer, expired, someone else)
and then branches:
- `ResolutionOffered` calls `record.resolve(...)`;
- `WithdrawalOffered` calls `record.withdraw(...)`.

Both pass `Report(by=name or id, channel=SLACK, note=said)`. A withdrawal the
store refuses because the incident has since ended is logged at info and
changes nothing. D7 has already taken the button away by then, and the press
is the backstop.

### D6. The wait

`_unanswered` now counts a message as answered when:
- it was understood as asking for no ending (anything but `resolve` or
  `withdraw`);
- it was understood as asking for an ending the incident's current status no
  longer accepts, whether or not it was offered; or
- its offer expired.

The second is new, and it is what covers the Code-Fix case in Context. It is
judged by the meaning rather than the offer, because a request the agent made
no offer for (the incident had already ended) is no more answerable than one
it offered too early. The wait
takes `status_of` beside `ended_by_a_person` to read the current status. A
press that ends the incident is caught first by `ended_by_a_person`, as it is
today.

### D7. Retiring offers by what they offer

The relay records a withdrawal offer's post as a `chat-withdrawal-offer`
reference. The existing kind is renamed `chat-resolution-offer`, because
`chat-offer` would otherwise mean only one of the two kinds of offer (one
word, one meaning). On a `StatusChanged`:
- to a status that does not accept a resolution: retire both kinds, as today;
- to any other terminal status: retire the withdrawal offers only.

An expiry still retires both. `NarrationLine` gains
`leaves_nothing_to_withdraw` beside `leaves_nothing_to_resolve`.

*Alternative:* the relay reads the offer events to tell the kinds apart. That
means linking each posted offer back to the person's message, which no
reference records. A second kind costs one constant.

### D8. Narration

- `WithdrawalOffered`: "Asked <name> to confirm Argus should stand down and
  put back what it changed".
- `OfferExpired` drops "to resolve" and becomes "The offer was not confirmed
  in time - carried on", because it now covers both kinds.
- The relay says `WithdrawalOffered` as `FOLLOWED`, in the thread, for the
  reason `ResolutionOffered` is.

### D9. Tests

- **One recording**, `intent-withdraw`, of the classifier answering the e2e
  case's message, made with `scripts/record_classification.py`: a single small
  paid call, run by the user.
- **One e2e case** (the user writes it), following the resolution case's
  order: hold, alert, write, seed, press. It asserts:
  - the incident is `withdrawn`;
  - no fix was looked for and no postmortem was written;
  - the account names the person, Slack and their words, and says nothing had
    been changed;
  - the offer was rewritten to say who withdrew it.
- The walks' recordings are untouched. The walk makes no new model call.
- The Code-Fix case is covered in module suites (the wait, the relay, the
  web), not e2e, because reaching it end-to-end would mean racing Code-Fix.

## Risks / Trade-offs

- [A misread message offers a withdrawal nobody meant] → Nothing changes until
  the person who wrote it presses, and the offer says what pressing does.
- [A withdrawal during `fixing` puts back a mitigation that worked] → This is
  how withdrawal already behaves from the UI, and the offer says so in as many
  words.
- [The offer is posted just after the incident ended] → The status change was
  relayed before the offer existed, so nothing retires it. A press is refused
  and logged, and the wait does not hold on it (D6). The button stays until
  the next retiring line. This is accepted: a button that does nothing when
  pressed is safe.
- [The reference-kind rename] → `chat-offer` rows written before the change
  are lost to `nox -s schema` like every other row, so nothing migrates.

## Migration Plan

No schema change: a reference kind is a value, not a column. The Slack app
needs nothing new, since the interactivity URL already receives every press.
