## Why

A person in an incident's Slack thread asks Argus something: "why did you
revert the flag?", "what have you tried so far?". Argus classifies the message
as a `question` and does nothing with it, so the one person reading the thread
asks and hears nothing back. Every other meaning the intent agent recognises now
acts; this is the last of the Slack-inbound changes.

## What Changes

- **A question is answered in its thread.** The intent agent answers each
  message it classifies as a question, in one model call, and the answer is
  posted as a reply in the incident's thread.
- **The answer comes from the incident's record and nothing else.** The model
  is given the incident's timeline - every recorded event, said as the page and
  Slack say it - and the question. It answers only what that holds, and says
  plainly when it does not hold the answer. It reads nothing live and can claim
  nothing Argus did not record.
- **The answer is an account, on the timeline.** It is published as an event,
  narrated like every other, and the relay posts it in the thread.
- **The walk is unaffected.** A question already lets a waiting walk carry on;
  answering it changes nothing about the incident.
- **Any incident can be asked about**, including one that has ended.

## Capabilities

### New Capabilities

- `slack-thread-question`: what a question written in an incident's thread is
  answered from, and how the answer reaches the person.

### Modified Capabilities

- `slack-thread-resolution`: a question is no longer "recorded and not acted
  on" - it is answered.

## Impact

- `agent_intent`: answering beside classifying, and the forced tool it answers
  through.
- `argus_core.events`: a `QuestionAnswered` event.
- `argus_narration`: a line for it.
- `agent_communicator`: the relay follows it into the thread.
- `docs/spec-and-architecture.md` §7.5a: the intent agent answers questions.
- e2e: one case, and an `intent-question` recording of the intent agent's two
  calls.
