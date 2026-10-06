## Context

`agent_mitigation/trying.py` polls metrics every 10s after an action and confirms on
`has_recovered_since`, with a deadline of the first whole minute + `minutes_a_recovery_must_hold`
+ the reporting lag. An irregular flap has no recurring gap, so one clear minute confirms.
Intake (`argus_web/grafana.py`) reads `alerts[0]`, ignores `status`, drops the rule identity,
and every webhook opens an incident. The demo app sends one hand-built firing alert per
scenario, evaluates no rule, and freezes each window three clean minutes after the fix.

## Goals / Non-Goals

**Goals:** the alert rule decides whether a series alert's mitigation held; no new Argus
setting; the defect reproduced and closed end to end; the replayed suite no slower.

**Non-Goals:** linking incidents; reopening a closed incident; judging the alert's own
definition (a threshold too strict, no data at night); own-finding alerts' confirmation.

## Decisions

- **The rule's state, not the webhook.** Polled through the read tier at the existing 10s
  cadence. Grafana batches resolved notifications by `group_interval` (5m default) and a
  webhook can be lost; a state read has neither problem, and it answers the case where the
  rule went normal before the action.
- **Confirm only on an evaluation whose range starts after the change was in force.** A
  rule that was already normal says nothing about the action. `lastEvaluation - range >=
  arrival` is the test, the arrival being when the change reached the service.
- **No early refutation from metrics.** Measured: a single minute back above the recovery
  bar occurs by chance after a genuine recovery (a +3-point error incident: 9% of incidents
  within an hour, 38% within six).
  A rule that averages over a long range is barely moved by one minute; a short-range rule
  is moved by exactly that minute, which is its definition of acceptable. The metrics are
  read only to date the recovery, and a window that cannot be read costs only that date.
  The cost: a failed candidate is found at the deadline rather than on its first bad minute.
- **Deadline = arrival + range + group interval + keep-firing-for + reporting lag.** Every
  term is the rule's own except the lag, which is the metrics source's. Read from
  `GET /api/v1/provisioning/alert-rules/{uid}` (`data[].relativeTimeRange.from`, seconds;
  `keep_firing_for`, snake case in that API) and the rule-group route (`interval`).
- **A rule whose evaluation measured nothing is unreadable, not normal.** Grafana's rules
  API reports a rule whose query failed or found no data as `inactive`, and says why only
  in `health`; read as normal it would confirm whatever was just done.
- **A vendor-neutral protocol, Grafana as an adapter.** `Alert` gains a rule reference that
  names no vendor; reading a rule's definition and state is a port, as deploy history is,
  and Grafana is its adapter. Grafana's webhook has no field naming the rule; the adapter
  reads its uid out of `generatorURL` - the segment after `/alerting/`, past a `grafana/`
  source segment where the link has one (releases build `/alerting/grafana/<uid>/view`, the
  documentation shows `/alerting/<uid>/edit`).
- **Merge by rule identity on an open incident.** A lookup in `argus_incidents` before
  `create`; the merged firing is answered with the open incident's id and records nothing.
  Closed incidents are not looked at: a later firing is a new incident.
- **Own-finding alerts keep today's path.** Their checks run on their own schedule (weekly
  reconciliation), so a resolve can be days away; in the fixture they never resolve.
- **The demo app evaluates a rule when its state is read,** the way its metrics are
  generated when read: no background loop. The last evaluation is the latest interval
  boundary at or before `datetime.now()`, which follows the simulated clock; the range is
  read over the generated window, which ends at the freeze, so a frozen scenario resolves
  rather than going to no data.
- **The tests keep posting the alerts,** standing in for the notifier, and add the rule
  reference. The demo app sending them itself would mean a background loop and every case
  finding its incident by polling - far more work for the same verdicts, since Argus reads
  the rule's state rather than the webhook.
- **Existing scenarios' rules are short enough to resolve inside the three clean minutes**
  without touching `CLEAN_MINUTES_SHOWN_AFTER_RECOVERY`, which recordings depend on.

## Risks / Trade-offs

- [A verdict flips in an existing e2e case, changing the walk's model-call sequence] → the
  double is a FIFO queue, so that breaks its recording; run the full `e2e_replay` before
  anything else and treat a flip as a finding, not a re-record.
- [The suite gets slower] → confirmation can only come one range plus one evaluation after
  the action; short rules keep that at today's first-clear-minute pace. Measured by the full
  run; a slower suite blocks the commit.
- [`generatorURL` is built from Grafana's root URL] → a misconfigured `root_url` makes a link
  nobody can open, but the uid is still read from its path; a sender that is not
  Grafana-managed may link no rule at all, and the levels decide. A real Grafana contract
  test is follow-up, not part of this change.
- [The range is read off the queries' time range] → that is the lookback of a range query
  reduced by an expression; a rule whose lookback lives inside an instant query's own
  expression is read as looking back only as far as its time range says.
- [The alert defines "acceptable"] → a flap mild enough not to keep the rule firing is
  reported mitigated, by design; the postmortem can recommend tuning the rule.
