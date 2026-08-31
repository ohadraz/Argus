## Why

Two of the five incident statuses currently say the opposite of what is
happening. A refuted mitigation is written as `fixing` while the walk goes on
looking for another explanation to try, and an incident that has run out of
explanations is written as `escalated` on its way *into* Code-Fix - so the one
status named after permanent fixes is spent on an incident nobody is fixing,
and the status that means "Argus is done, a human owns this" is set while Argus
is still working.

Nothing downstream corrects for it, because there is nothing to correct: both
values are persisted by `transition_incident` and, in the refuted case,
published as a `StatusChanged` event. The incident timeline and the dashboard
badge are the first readers of that record, and they now show a status the
incident never meaningfully occupied.

## What Changes

- A refuted mitigation self-loops on `mitigating` instead of leaving for
  `fixing`. It is still the same phase of the same incident: an action was
  taken, it did not help, and the next candidate is about to be tried.
- An incident with no explanation left transitions to `fixing` as it enters the
  Code-Fix node, instead of to `escalated`. `fixing` is the status of an
  incident a permanent fix is being sought for, which is exactly what Code-Fix
  is for.
- `escalated` is left to mean only what it should: Argus is out of moves and a
  human has been paged. It is reached from the Communicator's callers, not from
  the hand-off into Code-Fix.
- `IncidentStatus.FIXING.is_terminal()` stays `False`, but for the honest
  reason - Code-Fix is still working - rather than because it is a waypoint in
  the candidate walk.
- No new statuses, no removals, no schema change. The enum is unchanged; only
  which transitions write which member.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `incident-lifecycle`: the status an incident carries after a refuted
  mitigation, the status it carries when it reaches Code-Fix, and a new
  requirement that a status is written only when the incident actually enters
  it.

`incident-event-stream` is deliberately not listed. Its requirement is that a
status change publishes an event, and that stays exactly true - the spurious
`fixing` event disappears because the spurious transition does, not because
anything about publishing changed.

## Impact

- `modules/orchestrator/src/orchestrator/graph.py` - `_status_after`,
  `route_after_mitigation`, `route_after_next_candidate`, and the exhausted
  branch of `next_candidate_node`.
- `modules/argus_core/src/argus_core/models/incident_status.py` - the
  `is_terminal` docstring only; the return value is unchanged.
- `docs/spec-and-architecture.md` §10 - the state diagram's edges.
- Existing tests asserting `FIXING` after a refuted action, and the routing
  tests keyed on it, will need to move to `MITIGATING`.
- No database migration: the column stores the same enum, and historical rows
  keep whatever they were written with.
