## Context

The intent agent (`agent_intent`, its own process) works through the thread
messages nobody has understood yet, classifies each with one forced-tool model
call, records the meaning and publishes `MessageUnderstood`. Resolve and
withdraw become offers, information becomes a lead; a question stops there.

Everything Argus says in a thread is an event the relay (`agent_communicator`)
follows: it narrates the event with `argus_narration` and posts it as a reply in
the incident's thread. The incident's whole story is already readable as text:
`build_narration(events.get_by_incident(conn, incident_id))`.

## Goals / Non-Goals

**Goals:**
- A question gets an answer in its thread, from the incident's record.
- An answer the record cannot support is never given; "the record doesn't say"
  is an answer.

**Non-Goals:**
- Live reads. The model is given the record and calls no tool but the one it
  answers through.
- Conversation. Each question is answered on its own; earlier questions and
  answers reach the model only as lines of the timeline.
- Acting on a question. "Can you roll it back?" is answered, never done.
- Any change to the walk, the wait or the offers.

## Decisions

### D1. The intent agent answers

It already holds the message, the incident, a model and a replay log per
incident, and it is the agent people in the thread are talking to. A separate
answering process would read the same rows on the same loop.

*Alternative:* the Communicator. It has no model, and giving it one makes the
relay - which must keep posting when a model is down - depend on one.

### D2. One forced-tool call over the narrated timeline

`answering.answer(question, story, converse) -> str`, in a module of its own.
The opening message holds the question exactly as written and the incident's
timeline, one line per event: its time, who said it, its text - the lines the
page and Slack show, so the model reads the account a person could read. The
brief says: answer only from these lines; say so when they do not hold the
answer; never promise or describe an action as yours to take. The answer
arrives as the one field of `submit_answer`, so a reply is never parsed out of
prose. Asked at most twice, as classification is.

*Alternative:* hand the model the raw events. They are Argus's own vocabulary,
and an answer quoting a field name is an answer nobody in the thread can read.

### D3. Answered before the message is marked understood

`understand` works the answer out first, then records the meaning, then
publishes `MessageUnderstood` and `QuestionAnswered`. A process that dies
mid-answer leaves the message not understood, so the next pass asks again -
where answering after recording would leave a question marked understood and
never answered. A question the model cannot answer after the retry is
recorded as understood and answered with a fixed line saying Argus could not
answer it, with a warning: the person learns their question was read, as a
message that cannot be classified is recorded as none of these.

### D4. The answer is an account, not a record

`QuestionAnswered(message, answer)` is published like every other account, and
nothing is written to `thread_message`. Nothing decides on an answer - no wait,
no press, no agent - so a column would hold a fact only a reader of the event
log reads anyway.

### D5. Narration and the relay

The line is the Intent Agent's, says the answer whole, and is FOLLOWED: a reply
in the incident's thread, as the offers and weighings are. On the page it is
one more line of the timeline.

### D6. Every incident is answered

A question about an incident that has ended is still about something Argus
recorded. Only an incident Argus cannot find - which no message can belong to -
goes unanswered.

### D7. Recording

The e2e case seeds the intent agent's double with two answers: the
classification and the answer. `scripts/record_classification.py` records the
first; the second is recorded against an incident's real timeline by the same
script, given the incident to read. The incident comes free from a replayed
flag-toggle walk held open (`record_incident --replay --hold`), the same walk
the e2e case replays. The user records `intent-question` (the intent model;
cents).

## Risks / Trade-offs

- **The model answers past the record.** → The brief forbids it, the timeline
  is all it is given, and the e2e case asserts only that an answer was posted;
  whether it stayed inside the record is an eval question, and an eval pair
  (an answerable and an unanswerable question over one timeline) is the next
  coverage to add.
- **A long incident is a long prompt.** → Narration is one short line per
  event; the longest recorded walk is a few hundred lines. If it ever is not,
  the newest lines are the ones to keep, and that is a change of its own.
- **A question classified wrongly.** → A misread question gets a sentence of
  record back, which is harmless; a misread resolution is guarded by the press.
