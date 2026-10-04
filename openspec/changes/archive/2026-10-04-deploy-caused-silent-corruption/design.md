## Context

`silent-data-corruption` is answered today by a table entry:
`DEFAULT_STRATEGIES[SILENT_DATA_CORRUPTION] = RevertFeatureFlagStrategy()`. Every
other mode in that table names a kind of change or state, so mapping it to one
action is honest. This one names a kind of damage, and the mapping smuggles the
flag scenario's cause into Argus's policy.

What already holds, and does not change:

- The gate refuses the action as `NOTHING_COULD_CONFIRM_IT` from the evidence -
  stated onset, readings covering the incident, an action kind with no receipt -
  never from the action's identity. A rollback is refused exactly as a flag
  revert is, and the incident ends `RECOMMENDED`.
- The Investigator's change channels are already anchored on the stated onset,
  so a week-old deployment is in front of the model.
- `propose_action` is pure: every input arrives as a value, read once at the top
  of the round in `investigating.py` and carried in `IncidentState`.

## Goals / Non-Goals

**Goals:**
- The action for silent data corruption follows the change the record holds at
  the onset.
- A fixture that differs from the flag scenario in its change history only.
- No change to any tool the model sees, so no existing recording moves.

**Non-Goals:**
- Choosing between a flag and a deployment when both are recorded and the
  candidate names neither. That is `competing-flag-changes`' question in another
  mode, and the answer is the one that scenario already gets: nothing.
- A rolled-forward fix as the recommendation. A week-old rollback may discard
  later work, but the recommendation is read by a person who can see that, and
  Code-Fix's PR is already the roll-forward beside it.
- Fixing the known `withdraw_the_rollback` asymmetry. Nothing here takes the
  rollback, so there is nothing to withdraw.

## Decisions

**1. One mode, a strategy that chooses - not a new mode.**
`SILENT_DATA_CORRUPTION` maps to a new `UndoTheRecordedChangeStrategy` (name
open) holding the flag revert and the rollback. It proposes the flag revert where
the flag revert would propose something, else the rollback where a deployment is
recorded, else `None`.

*Alternative:* a tenth mode for deploy-caused corruption. Rejected: the mode is
what the incident *is*, and a reader who must already know the cause to name the
mode has had the investigation done for them. It would also leave the flag
scenario's mapping exactly as wrong as it is now.

*Alternative:* fall back to the rollback whenever no flag is found, with no
deploy record read. Cheaper - no new read - and rejected because "no flag" is
not "a deployment": it would recommend undoing a revision for a fault a
migration or a console edit caused.

**2. Flag first, by the record rather than by preference.** The flag revert
answers only where a recorded change matches the candidate's subject, or is the
only flag change in the window - a much narrower condition than "a deployment
exists", since an estate deploys far more often than it toggles. So a flag
match is the more specific evidence and is asked first.

**3. The deploy history is a walk-level read, like the flag history.**
`fetch_recent_deployments` in `agent_mitigation.tools`, beside
`fetch_recent_flag_changes` and shaped like it - the same lookback, the same
`onset` anchor - over the read tier's `get_change_events`. Argus's own rollbacks
are not dropped: the one reader is a mode whose action is never taken. Read in `investigator_node` in the same breath as the flag
history, carried as `IncidentState.deployments: list[ChangeEvent] | None`, and
handed to `propose_action` in `proposing.py` and `candidates.py`.

*Alternative:* let the strategy read the deployments off the Investigator's
findings. Rejected: the findings are the model's reading of the record, and the
flag revert already refuses to take its direction from prose.

**4. The protocol grows a defaulted keyword, as it did for the keys.**
`MitigationStrategy.propose(..., deployments: Sequence[ChangeEvent] = ())`. Six
strategies ignore it, which is the same trade the `stale_entry_keys` default
made - a required parameter would have every call site naming an input that
answers nothing for it.

**5. Fixture: a deploy-staged scenario reusing the drift machinery.**
`drifts_the_monthly_total=True` and a `ScenarioDeploy` whose revision is a new
commit on an unmerged branch (the control-plane scenario's pattern). Two things
in `state.py` must follow the deploy rather than the flag: the flag history is
backdated only where no deploy carries the drift, and the deploy entry is
backdated to the drift's onset. The platform stand-in's rollback stops the
drift.

## Risks / Trade-offs

- [The model calls it `bad-deployment`] → same rollback, same `RECOMMENDED`, so
  the near-miss is invisible to the e2e case. Carried by an Investigator eval
  case, as the half-finished rollout's near-miss is.
- [Code-Fix reads main, where the fault is behind a flag, not the deployed
  revision] → the fix to main's write path is the same fix; the PR is right for
  the shop that runs. Worth one line in the scenario's description so the
  divergence is not rediscovered.
- [A new read on every round of every walk] → it is the same tool the
  Investigator already calls, against the same stand-in, and an unreadable
  history only removes the rollback for this one mode.
- [Existing recordings] → the read is the walk's, not the model's, so no corpus
  moves; the free `e2e_replay` over every scenario is what proves that before
  anything is bought.

## Names

- The scenario is `monthly-totals-falling-behind` - named for the data rather
  than the cause, by the convention `silent-data-corruption` sets.
- The strategy is `UndoTheRecordedChangeStrategy`.
