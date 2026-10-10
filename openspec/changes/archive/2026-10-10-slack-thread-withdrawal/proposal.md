## Why

A person who takes an incident over from Argus says so where they are already
talking about it: in its Slack thread. Argus classifies that message as
`withdraw` today and does nothing with it, so "stop, I've got this" leaves
Argus working, and maybe changing things, under a person who asked it to
stop. This is the second of the Slack-inbound changes. It acts on `withdraw`
the way the first one acts on `resolve`.

## What Changes

- **A request to stand down is offered before it is acted on.** Where a
  message is classified as `withdraw` and the incident can still be withdrawn,
  Argus replies in the thread with a button that only the writer can press. The
  reply says what pressing it does: Argus stops, and puts back what it changed.
- **The press withdraws the incident** as the Argus UI does, credited to the
  person by their Slack name (or their Slack id), through Slack, with their
  message as the note. The walk stops and unwinds, as for any withdrawal.
- **No offer on an ended incident**, as for a resolution.
- **The walk waits for this answer** as it waits for a resolution's (5
  minutes, from the message). It stops waiting on any offer the incident no
  longer accepts.
- **An offer is retired once the incident no longer accepts what it offers.**
  A withdrawal offer loses its button at any terminal status. A resolution
  offer keeps its current rule.
- **One confirm button for every offer.** The button's action id no longer
  names resolving. The offer, found by its message, says what is being
  confirmed.

## Capabilities

### New Capabilities

- `slack-thread-withdrawal`: a person withdraws an incident by asking Argus to
  stand down in its Slack thread and then confirming. Covers when a withdrawal
  is offered, who may confirm it, and what the withdrawal leaves.

### Modified Capabilities

- `slack-thread-resolution`: the walk's wait covers withdrawal offers too, and
  stops waiting on an offer the incident no longer accepts. An expired offer is
  said generically, not as "the offer to resolve".
- `slack-communication`: the withdrawal offer is posted in the thread. An
  offer is retired when the incident no longer accepts what it offers.
- `incident-withdrawal`: Slack is a channel a withdrawal may come through,
  credited to the person who confirmed it.

## Impact

- `argus_core`:
  - the event `WithdrawalOffered` (the shape of `ResolutionOffered`);
  - `IncidentStatus.accepts_withdrawal()`;
  - the offer reference kinds split, one per ending (`chat-resolution-offer`,
    `chat-withdrawal-offer`).
- `agent_intent`: on `withdraw`, it offers.
- `argus_incidents`: the wait (`waiting.py`).
- `argus_web`: a press confirms whichever offer it answers.
- `chat_platform`: the action id becomes `confirm-offer`.
- `agent_communicator`: the new lines, button labels per offer, and
  retirement per ending.
- `argus_narration`: a line for the new event. The expiry line no longer says
  "to resolve".
- Tests: one recording, `intent-withdraw` (a single small paid call), and one
  e2e case (the user writes it). The walks' recordings are unchanged.
- `docs/spec-and-architecture.md`: §7 (the Intent Agent) and §16.
