## Why

A person who knows something Argus does not says it in the incident's Slack
thread: "it's the checkout flag, not the other one". Argus classifies that
message as `information` today and does nothing with it, so an expert's lead
reaches the timeline and no agent. This is the third of the Slack-inbound
changes, and the one benchmark scenario 7 (spec §21) exists to test: whether
Argus incorporates human input.

Doing it exposes a debt the first two changes left. The walk's wait and the
press both decide on events, which the event stream's own requirement forbids
("no decision may depend on a published event"). Feeding a lead to the
Investigator from the event log would make that three. So the conversation
moves into the incident record first, and everything that decides reads it
there.

## What Changes

- **The conversation is part of the incident record.** What a person wrote,
  what it was understood to mean, what was offered and whether the offer
  expired are rows, not only events. Each row and its event are written in one
  transaction. The wait, the press and the agents read the rows; events go back
  to being an account only.
- **A lead reaches every model-backed agent.** The Investigator, Code-Fix and
  the Postmortem are each given every lead written so far when they start, and
  the two tool loops are given any lead understood since their last turn on the
  next tool result. Mitigation has no model; a lead reaches it through the
  hypothesis it shaped.
- **A lead is weighed, never obeyed.** The Investigator gives each lead a
  standing: *supported* by what it read, *refuted* by what it read, or
  *unverified*, neither. A refuted lead is not acted on. An unverified lead may
  still become a candidate, ranked by the model at the confidence it earns, and
  goes through the tier gate like any other.
- **The person is told what Argus made of it.** Each standing is narrated and
  posted in the thread with its reason.
- **Code-Fix gets each lead with its standing**, and a lead the Investigator
  never saw as unweighed context. It gives no standing of its own.
- **A lead after the investigation does not reopen it.** It reaches Code-Fix
  and the Postmortem; a refuted mitigation sends the walk back to the
  Investigator anyway, which then weighs it.
- **The postmortem says what people told Argus**: each lead, its standing, and
  whether it changed what was done.

## Capabilities

### New Capabilities

- `slack-thread-information`: what a lead written in an incident's thread
  reaches, how it is weighed, and what the person is told about it.

### Modified Capabilities

- `slack-thread-resolution`: a person's message, its meaning, an offer and its
  expiry are recorded on the incident, and the wait and the press read that
  record rather than the event log.
- `incident-postmortem`: the document reports what people told Argus.

What the Investigator, Code-Fix and the thread do with a lead is stated once,
in `slack-thread-information`, rather than split across their own capabilities.

## Impact

- `argus_core`: migration `001` gains the conversation table; a `Standing`
  value; events `LeadWeighed`; the `events.py` docstring is true again.
- `argus_incidents`: a `conversation` repository; ingestion writes the row; the
  wait reads rows.
- `agent_intent`: classification and offers are written to the row with their
  events.
- `argus_web`: the press finds its offer on the row.
- `orchestrator`: the walk hands each agent the leads, and the two loops a way
  to ask for new ones.
- `agent_investigator`: leads in the opening message and between turns; a
  `weigh_lead` tool; `final_answer` refused while a lead shown is unweighed.
- `agent_codefix`: leads in the opening message and between turns.
- `agent_postmortem`: a section of leads in the evidence and the document.
- `argus_narration`, `agent_communicator`: a line and a thread post for a
  standing.
- Tests: one intent recording (`intent-information`, a single small paid call)
  and two walk recordings on the demo app's existing `competing-flag-changes`
  scenario, one with the lead posted before the walk and one with it posted
  mid-investigation (the user runs them; paid). An eval pair, with and without
  the lead, measures whether the real model is moved by it (paid). Existing
  recordings are unchanged. No demo-app code.
- `docs/spec-and-architecture.md`: §7.2, §7.4, §7.5, §7.5a, §7.6, §7.9, §11 and
  §21.
