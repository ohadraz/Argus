## Why

`silent-data-corruption` stages FM-26 with a flag as its cause, and Argus answers
it with the flag revert - but it answers it that way because
`DEFAULT_STRATEGIES` maps the mode to `RevertFeatureFlagStrategy`, not because
the evidence named a flag. The same damage arriving from a deployment has the
same symptoms and a different action, and today Argus would propose a flag
revert with no flag change behind it, find nothing to reverse, and escalate
having recommended nothing. A walk that reads a flat window and reaches for a
flag has learned the scenario rather than the mode. This is the backlog's first
entry, in the family with the largest uncovered share left (foundational
integrity, 12%).

## What Changes

- **A second scenario under FM-26 in the Target Service**: the same monthly
  total falling behind its purchases, the same weekly integrity check, the same
  alert carrying the oldest affected purchase as the onset - and a deployment at
  that onset rather than a flag. The deploy history holds the entry; the flag
  history holds nothing; the window is flat throughout.
- **The deployed revision is a pair of real commits on a branch of their own**,
  never merged, whose diff shows the monthly addition removed unconditionally.
  Main is untouched, so the fix corpus and every scenario reading main stay
  frozen.
- **Silent data corruption's mitigation is chosen by the change the evidence
  records, not by the mode.** The mode says the data is wrong; which change
  caused it is what decides the action. A flag change at the onset is answered
  by putting the flag back, a deployment at the onset by returning the
  deployment, and neither by nothing - which escalates, as it should, rather
  than recommending a rollback of a deployment nobody made.
- **The walk reads the deploy history beside the flag history**, once at the
  top of the round and anchored the same way, so the choice above is made from a
  record rather than from the model's prose. No tool the model sees changes, so
  every existing recording stays valid.
- **The ending is still `RECOMMENDED`**, for a reason the kind of change has
  nothing to do with: the window is flat throughout, so its minutes will read
  the same after the change goes back, and nothing inside the verification
  window could judge it. The gate already decides this from the evidence and not
  from the action, so it does not change.
- **The near-miss is `bad-deployment`**, and it reaches the same action and the
  same ending - so it is refuted in the record only, as the half-finished
  rollout's is. An Investigator eval case carries it.

## Capabilities

### New Capabilities

- `deployed-data-integrity-scenario`: the Target Service staging the monthly
  total's drift from a deployment - what the deploy and flag histories hold,
  what the diff shows, what returning the deployment stops and what it leaves.
- `corruption-mitigation-choice`: which action answers silent data corruption,
  read off the change recorded at the onset, and why neither change recorded
  answers with nothing.

### Modified Capabilities

- `investigator-cause-detection`: silent data corruption is named whichever kind
  of change sits at the stated onset, and a flat window with a reconciliation
  finding and a deployment at the onset is not a bad deployment.

## Impact

- `agent_mitigation`: a strategy for `SILENT_DATA_CORRUPTION` that holds both
  the flag revert and the rollback and picks between them; `propose_action` and
  the strategy protocol gain the deployments recorded, defaulted so no other
  strategy reads them.
- `orchestrator`: the deploy history read at the top of the round beside the
  flag history, carried in `IncidentState`, and handed to `propose_action` in
  both places that call it (`proposing.py`, `candidates.py`).
- `Argus-Demo-Target-App`: the scenario, the two commits on their own branch,
  the deploy entry backdated to the onset with no flag history behind it, the
  console entry, and a harness test that returning the deployment stops the
  drift and repairs nothing.
- Recordings: one new `both-` corpus. Nothing existing moves.
- Evals: an Investigator case for the mode named from a deployment.
- `docs/failure-modes-backlog.md`: FM-26 gains its second member, and the
  backlog's "next" list moves up.
