## Why

The Postmortem is a stub: it returns fixed strings and two nulls, and the
orchestrator already calls it on every terminal transition. The evidence a real
one needs is largely sitting in Postgres already - the event stream, the ranked
candidates, the actions and their verdicts, the replay log - and is being
thrown away at the last step of every incident.

Two of its figures need sources Argus does not have yet (revenue, and responder
timings). Building those first would mean guessing what the agent wants before
anything asks. So the agent comes first, taking both as injected collaborators,
and each real source lands afterwards as a swap behind an established seam.

## What Changes

- The Postmortem agent computes its figures rather than reporting nulls:
  duration and timeline from the incident's own rows, `tokens_spent` from the
  replay log, `engineer_minutes` and responder count from a responder port, and
  `customer_loss_estimate_usd` from a revenue port plus the metrics it re-reads
  for a window the Investigator never covered.
- **The arithmetic is deterministic and the model supplies no number.** One
  `converse` call produces prose only: root cause, assumptions, executive
  summary - and `impact_weight`, which is a disclosed judgment rather than a
  measurement.
- Two ports are introduced with fakes behind them - **revenue in a window** and
  **who responded and when**. Nothing real answers them in this change; each
  gets an adapter in its own change afterwards.
- The completeness self-check of spec §7.6: the agent checks its own document
  against a checklist, retries once with the missing fields named, then hands
  off regardless. It must terminate on partial success.
- **BREAKING** for callers of `agent_postmortem.write_postmortem`, whose return
  stops being a dict of placeholders. The orchestrator is the only caller.

## Capabilities

### New Capabilities
- `incident-postmortem`: what the Postmortem agent produces on a terminal
  transition - which figures are measured, which are estimated and disclosed as
  such, that the model supplies prose and never a number, and that the agent
  terminates even when the document is incomplete.
- `postmortem-evidence-sources`: the two ports the agent reads through -
  revenue in a window, and responder timings - defined by what the agent needs
  rather than by what any provider offers, so an adapter satisfies a seam that
  already exists.

### Modified Capabilities
- `incident-lifecycle`: an incident records when it ended, at the transition
  that ended it, so how long it lasted is a fact rather than an inference from
  whichever row happened to be written last.

<!-- The stub itself was never specced; the postmortem row, its repository and
     its page already exist and do not change. -->

## Impact

- `modules/agent_postmortem/` - the agent, the ports, the arithmetic, the
  checklist. Currently 20 lines.
- `modules/orchestrator/` - the graph node persists a real postmortem row
  instead of placeholder content.
- `incident` gains `ended_at`: duration is a figure the postmortem reports, and
  deriving it from the last timeline event would make it an accident of what
  happened to be logged last. `postmortem` itself already carries every column
  this writes.
- No new third-party dependency, and no new process.
- Cost: one model call per incident, on a path that runs once per incident.
