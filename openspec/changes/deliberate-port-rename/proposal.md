## Why

`monitoring-blind-spot` stages a revision that renamed the shop's metrics port by
accident, and answers it by returning the revision. The same silence where the
rename was *meant* - one step in naming every port for its protocol, with the
scrape configuration left behind - has no revision worth returning: putting it
back undoes work somebody intended, and what is broken is the monitoring's own
configuration. It is the largest unbuilt remainder of FM-27, and the first mode
whose correct ending is a proposal with the sight still lost.

## What Changes

- **`FailureMode.MONITORING_CONFIGURATION_DRIFT`** - an eleventh mode. The service
  is well and was deliberately changed; the configuration that observes it was
  not changed with it. Separated from `monitoring-blind-spot` (same arrival, but
  the change was a mistake and returning it is the answer) and from
  `config-induced-failure` (the service's own configuration is broken).
- **No strategy answers it.** What is wrong is a file in the repository, and
  nothing Argus may do reaches a file - returning the revision would restore the
  sight by undoing the intent.
- **A mode nothing answers ends the mitigation phase.** Today the refusal moves
  the walk to the next candidate, and in this mode the next candidate is reliably
  the rollback (a paid blind-spot walk ranked `config-induced-failure` second, on
  the same subject). A refused leading explanation is the diagnosis saying no
  mitigation applies; acting on a less likely one contradicts it. The walk goes
  to Code-Fix instead, without spending its remaining rounds. **BREAKING** for
  `upstream-dependency-failure`'s walk, which takes this route too, so its
  recordings are re-recorded.
- **The scrape configuration becomes a real file** in the Target Service's
  repository, beside the values file, selecting the metrics port by a name the
  values file no longer carries on `main`. The fix rolls it forward, and brings a
  test in `tests/io_shop` that reads both files and fails until they agree.
- **Code-Fix can find it.** `GITHUB_SOURCE_PATHS` gains `deploy`, the deployment
  configuration being the service's as much as its source.
- **A second revision pair** renaming several ports to one convention in one
  commit, staged on an unmerged branch. What tells the two scenarios apart is the
  diff the Investigator already reads: one name changed alone, or every name
  changed to a rule.
- **The postmortem says the sight was never restored** - that the incident closed
  with the minutes after its onset still uncollected - rather than reporting the
  window it could read as the incident.

## Capabilities

### New Capabilities

- `monitoring-configuration-drift-scenario`: the Target Service staging a
  deliberate port rename the scrape configuration did not follow - the revision
  pair, the scrape configuration file, why returning the revision is not the
  answer, and that nothing but a merged change ends the silence.

### Modified Capabilities

- `investigator-cause-detection`: monitoring configuration drift is a determinable
  mode, and the evidence separating it from a blind spot is the shape of the
  change.
- `mitigation-retry-walk`: a candidate refused because nothing answers its mode
  ends the walk's mitigation phase rather than passing to the next candidate.
- `incident-status-derivation`: such a walk ends `escalated`, with or without a
  fix.
- `code-fix-agent`: the deployment's configuration is in the source scope the
  agent reads and searches.
- `incident-postmortem`: an incident that closed without its sight restored says
  so.

## Impact

- `argus_core.models`: the mode and its `meaning()`.
- `orchestrator`: the gate's route after `NOTHING_ANSWERS_THIS_MODE`, and the
  status it derives.
- `agent_investigator`: nothing beyond the mode list the model is offered.
- `agent_postmortem`: the closing-without-sight line.
- `noxfile.py`, `.env.example`: `GITHUB_SOURCE_PATHS` gains `deploy`.
- `Argus-Demo-Target-App`: the scrape configuration on `main`, the revision pair
  on an unmerged branch, the scenario id, its seed and reset.
- `github_double`: `main` carries `deploy/`. Off-limits - proposed in chat.
- Recordings: a new corpus for the scenario; `upstream-dependency-failure`'s
  re-recorded for the shorter walk. Both paid.
- `tests/e2e`: a case asserting the mode, no rollback, a proposed fix, the sight
  still lost, and `escalated`. Proposed in chat.
