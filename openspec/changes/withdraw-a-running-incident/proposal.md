## Why

An incident Argus is walking cannot be stopped. Nothing in the walk reads the
incident back, so a human who has already fixed the failure themselves can only
watch: Argus goes on to toggle a flag on a service that is healthy again, waits
out its verification window, sees the recovery the human caused, and records the
mitigation as its own. "Stop, I have this" is the first thing anybody wants from
an autonomous responder during an incident, and Argus has no door for it.

The same missing door is why `e2e_replay` is unreliable. A case ends when its
own assertion holds, not when the walk does - the webhook answers `202` as soon
as the incident exists - so the previous case's walk is still running when the
next one resets the world and seeds the Anthropic double, and drains answers
that were not meant for it. The suite cannot stop what it started, so it either
waits out a whole walk it has no interest in or races it.

## What Changes

- An incident can be **withdrawn**: a terminal status meaning a human took the
  incident back, distinct from resolved (Argus fixed it) and escalated (Argus
  could not).
- The walk honours withdrawal **between steps** - at every node boundary and
  inside the recovery-verification loop, which already wakes every ten seconds -
  and stops without reaching its next action. A model call already in flight
  runs to completion; nothing is acted on afterwards.
- A worker **refuses to claim** a run whose incident was withdrawn before
  anything picked it up.
- Withdrawal **puts back what Argus changed**: every action recorded as taken is
  undone, conditionally. A flag is reverted only if it still holds the value
  Argus wrote; a flag somebody has since changed is left alone and reported as
  overridden. A blind restore would clobber a deliberate human change, which is
  the exact thing withdrawal exists to respect.
- The timeline says all of it: that the incident was withdrawn and by whom, what
  Argus had done by then, and for each undo step whether it was put back or
  found already changed from the outside.
- The incident page offers withdrawal while an incident is live.
- The e2e suite's teardown withdraws through that same door, waits for the run
  to settle, and then empties every table - so a case leaves the world as it
  found it instead of leaving its incidents, hypotheses, actions, timeline,
  events, replay entries and postmortems behind for every later case to read.

## Capabilities

### New Capabilities
- `incident-withdrawal`: withdrawing a live incident - who may, what the walk
  does when it sees it, how far it may still go, and what it leaves behind.
- `conditional-action-undo`: putting back a reversible action only where the
  world still holds what Argus left there, and saying so when it does not.

### Modified Capabilities
- `incident-lifecycle`: `withdrawn` joins the terminal statuses, reachable from
  every live status and from none of the terminal ones.
- `incident-status-derivation`: withdrawal is set from outside the walk rather
  than derived from its state, and overrides the status the walk would derive.
- `mitigation-retry-walk`: a walk ends when its incident is withdrawn, without
  trying its remaining candidates or its next round.
- `flag-revert-mitigation`: a revert is conditional on the flag still holding
  what Argus set, and reports an outside change rather than overwriting it.
- `e2e-replay`: each case withdraws what it started and empties the database,
  so cases neither share a walk nor read each other's rows.
- `live-incident-view`: a live incident can be withdrawn from its page.

## Impact

- `argus_core`: `IncidentStatus` gains `withdrawn`; `status_after` respects it.
- `orchestrator`: `graph` checks withdrawal at node boundaries and runs an undo
  path; `worker`/`runs` refuse to claim a withdrawn incident; `repository`
  gains the withdrawal write and the read the walk polls.
- `agent_mitigation`: the verification loop checks withdrawal beside recovery;
  `_undone` becomes conditional.
- `write_mcp_server`: the flag write's undo descriptor is what the conditional
  revert compares against.
- `argus_web`: a withdraw control and its endpoint on the incident page.
- `tests/e2e/conftest.py`: withdraw, wait for the run to settle, truncate.
