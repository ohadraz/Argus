## Why

An investigation begins by reading the metrics window, before the model is asked
anything. Where that window holds no departure in any judged series and the alert
states no onset, the loop stops and reports that no cause was determined - and
the walk ends `ESCALATED` with a postmortem, which is the same ending an incident
gets when Argus read every channel and could not work out what was wrong.

Those are different sentences and a responder acts on them differently. *I could
not find the cause* says go and look at the service. *Nothing is wrong with the
service and the alarm was mistaken* says go and look at the rule. Argus already
knows which one it is holding - the window it just read is the contradiction - and
reports both as a handover.

The same branch is the one an alert carrying its own finding would fall into if
it happened to carry no date: a check that compares stored values against the
records behind them can find a disagreement it cannot date, because what would
date it is what went missing. A window with no departure contradicts nothing there
- the series were never the subject - so an ending that closes a flat window as
disproven must not be reached by looking at the window alone. What a window can
contradict is a claim about a series, which is why the split is on what the alert
claims rather than on what the metrics show.

## What Changes

- **An alarm the metrics contradict is closed as `disproven`, and that is a fourth
  ending.** Argus states what it read, states that the alarm's own claim is not in
  it, and stops. No candidate is formed, nothing is mitigated, no fix is sought
  and nobody is handed an incident to investigate.
- **The split is on the alert's claim, not on the window.** An alert reporting a
  series departing - an error rate, a latency, a resource - can be contradicted by
  that series, and a window with no departure in any judged signal does so. An alert
  reporting a finding of its own - stored values that disagree, readings that
  stopped arriving - claims something no series carries, so a flat window is not
  evidence against it and the investigation goes on.
- **An alert says which of the two it is, rather than having it inferred from its
  name.** Matching on `alertname` would make the distinction a string table that
  every new rule in the estate has to be added to, and would get a rule named
  after its service wrong. What the alert carries instead is whether it is
  reporting a condition it measured on a series or a finding of its own; the three
  rules that already speak here - the integrity check, the cache reconciliation,
  the absence of readings - are exactly the ones that carry a finding.
- **`DISPROVEN` is the status, derived rather than decided.** A node does not get
  to set it: the status function reads that the alarm was disproven, the way it
  reads that an action was named and not taken for `RECOMMENDED`. The word is not
  `refuted`, which is already this system's term for a mitigation attempt the
  evidence undid - one word with two meanings is a cost paid by every later reader.
- **A postmortem, as every other ending gets.** The invariant holds: one document,
  written on the transition that ends the incident, whatever the ending. What was
  ruled out is what the next responder needs, and here what was ruled out is the
  alarm itself - so the document says which series the rule named, what the window
  held instead, and that the rule rather than the service is what to look at.
- **Breaking for nothing, which took a run to establish.** The obvious candidate
  was `test_firing_alert_with_no_cause_to_find_escalates_with_a_postmortem`: no
  scenario seeded, a `HighErrorRate` alert, and what reads like a well shop. It is
  not one. An unseeded Target Service serves no metrics at all, so that window is
  empty rather than flat, and an empty window is an indication of nothing in
  either direction. That case keeps `INVESTIGATING` → `ESCALATED` and is renamed
  to say why - `test_an_alert_over_a_window_nobody_could_read_escalates_with_a_postmortem`.
  The disproof gets a case of its own beside it, seeding `silent-data-corruption`
  for a window that is present and flat in all five judged signals and firing the
  suite's own plain alert, which states no onset and claims nothing about what it
  watched. Nothing else green reaches the branch: all three modes with a flat
  window state an onset, so they take the branch that already exists for one.
- **The second half is a seam and not a feature.** An alert carrying a finding with
  no onset goes on to the model instead of stopping. No scenario produces one
  today, and the mode that would - data lost rather than written wrongly, dateless
  because the evidence that would date it is what was deleted - is proposed
  separately or not at all. What this change owes it is that the branch exists and
  is reachable, so the ending above cannot swallow it.

## Capabilities

### New Capabilities
- `disproven-alarm-closure`: which alarms a metrics window can disprove, what
  counts as disproving one, the ending a disproven alarm gets, and what its
  postmortem says.

### Modified Capabilities
- `investigator-react-loop`: the metrics read before the loop now answers two
  questions rather than one - whether there is an onset, and whether the alert's
  own claim is one this window could have contained.
- `alert-supplied-onset`: an alert that states no onset is no longer one case. One
  reports a series and can be contradicted by it; one reports a finding and
  cannot, and the second goes on without a date.
- `incident-status-derivation`: a disproven alarm derives `DISPROVEN`, and does so
  from the state rather than from a node's say-so.
- `incident-lifecycle`: a fourth ending beside mitigated, escalated and
  recommended, and the transitions that reach it.
- `incident-postmortem`: the document an incident that never was is written up as.
- `slack-communication`: what a human is told when the alarm rather than the
  service was wrong.

## Impact

- `modules/argus_core`: the new `IncidentStatus` member; what an `Alert` says about
  the kind of claim it carries; the status derivation.
- `modules/agent_investigator`: the branch taken when the window holds no departure,
  split by the alert's claim.
- `modules/orchestrator`: the walk's investigating step and the end it reaches.
- `modules/argus_narration`: a line for a disproven alarm.
- `modules/argus_web`: the Grafana reader passes the new field through; the
  dashboard shows the new status.
- `Argus-Demo-Target-App`: the annotation the three finding-carrying rules set.
- `tests/e2e/test_incident_lifecycle.py`: the case above, re-asserted.
- `docs/spec-and-architecture.md`: the ending, in §10's list of what an incident
  can end as.
