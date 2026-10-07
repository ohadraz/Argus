## Why

FM-17, output-quality degradation, is the one mode in the AI-specific family that
Argus could build, and today it would close such an incident as disproven: the
rule that pages watches a quality series Argus never reads, the five series
Argus judges stay flat, and a flat window under a series alarm is read as
evidence that the rule was wrong. The rule is the one thing that knows what it
watched, and Argus already reads the rule - it just never reads *what* it
watches.

## What Changes

- **The paging rule's own series joins the window.** Where an alert names a
  rule, the read tier reads that rule's definition from Grafana - the query it
  evaluates and the comparator its threshold applies - fetches the query's
  per-minute values from Prometheus, and carries them on every `MetricBucket`
  beside the fixed signals.
- **That series is judged.** Onset, departure and recovery read it as a sixth
  judged signal, in the direction its rule says is worse: above the threshold for
  a `gt` rule, below it for an `lt` rule. A quality share that falls departs.
- **A rule whose series could not be read disproves nothing.** An alert naming a
  rule whose series the read tier could not resolve or fetch is not closed on a
  flat window: the window was never shown what the rule watched.
- **A new failure mode, `output-quality-degradation`.** A change made the
  service's answers worse while every request still succeeds as fast as before.
  Answered by the existing deployment rollback, as three other modes already are.
- **The postmortem reports the rule's series** - its level before the onset,
  while broken and at its worst - beside the error rate, which for this mode
  never moves.
- **The dashboard and the narration show the rule's series** as a column of the
  evidence where it was read.
- **The Target Service stages it.** Io's purchases gain a categoriser; a deployed
  model upgrade, v1 to v2, ships with a preprocessing mismatch, so most purchases
  are filed under "General". The shop publishes the share categorised
  confidently, and a new rule pages when it falls below its threshold. The
  shop's Grafana stand-in learns the `lt` comparator, and every rule definition
  carries the PromQL query its Prometheus stand-in answers, in place of a field
  name.
- An e2e case, a recording, a graded fix, an eval case, the spec and the
  backlog.

## Capabilities

### New Capabilities
- `paging-rule-series`: reading the series the paging rule evaluates - resolving
  it from the rule's definition, fetching it, carrying it on the metrics window,
  and judging it in the rule's direction.
- `output-quality-degradation-scenario`: the categoriser model upgrade the
  Target Service stages, its telemetry, its rule, its deployed revision and the
  fault Code-Fix fixes.

### Modified Capabilities
- `metrics-source`: a window may carry the paging rule's series beside the fixed
  fields.
- `trend-onset-detection`: the paging rule's series is a judged signal, in the
  direction its rule names.
- `disproven-alarm-closure`: an alarm whose rule's series could not be read is
  not disproven; a disproof names the rule's series among the signals judged.
- `investigator-cause-detection`: output-quality degradation is a determinable
  mode, told apart from a bad deployment.
- `deployment-rollback-mitigation`: rolling back answers output-quality
  degradation.
- `incident-postmortem`: the paging rule's series is reported beside the error
  rate.
- `incident-dashboard`: the evidence shows the paging rule's series.
- `target-service-alert-rules`: a rule definition carries its PromQL query and
  its comparator, and a rule may fire below its threshold.
- `target-service-prometheus-api`: the stand-in answers every query a rule
  definition names.

## Impact

- `argus_core`: `MetricBucket` gains an optional rule reading; `anomaly` judges
  it; `FailureMode` gains a value and its meaning.
- `metrics_source`: the adapter fetches one more query when given one.
- `read_mcp_server` / `read_mcp_client`: `get_metrics_summary` takes the rule
  that paged; the rule-definition read resolves the query and the comparator.
- `agent_investigator`: passes the rule, guards the disproof, describes the
  column.
- `agent_mitigation`: passes the rule when polling, so the recovery is dated on
  the rule's series; `DEFAULT_STRATEGIES` maps the mode to the rollback.
- `agent_postmortem`, `argus_narration`, `argus_web`: the new figure and
  column.
- `Argus-Demo-Target-App`: the categoriser, the scenario and its `deploy/*`
  revision pair, the series, the rule, the stand-ins.
- `tests/e2e`, `tests/contract/prometheus`, `tests/eval`, `scripts/
  record_incident.py`, `noxfile.py`, one paid `both` recording.
- `docs/spec-and-architecture.md`, `docs/failure-modes-backlog.md`.
