## Context

Argus reads a fixed set of Prometheus series (`metrics_source/prometheus_adapter.py`
`QUERIES`) into fixed-field `MetricBucket`s and judges departures on five of them
(`argus_core/anomaly.py` `_THE_SERIES_A_DEPARTURE_APPEARS_IN`), always as "higher is
worse". The read tier already reads the paging rule from Grafana
(`read_mcp_server/alert_rules.py`), but only its range, interval, keep-firing period
and state - never the query it evaluates or the comparator its threshold applies.

So a rule paging on a series outside the fixed set - an ML model's confidence, an
LLM's refusal rate, any quality measure - reaches an Investigator that sees five flat
series and closes the alarm as disproven (`investigation.py:370-385`). FM-17,
output-quality degradation, is exactly that incident: "model outputs degrade in
quality without a clear service error - latency looks normal, error rates stay flat"
(stackgen's taxonomy, the backlog's source).

Two decisions were the user's and are settled: the series is read from the rule
itself rather than added as a named field, and the shop's signal is a confident
share that *falls*, so direction is read from the rule too. The change is a deployed
model upgrade, rolled back; the postmortem reports the rule's series.

## Goals / Non-Goals

**Goals:**
- An alert naming a rule brings that rule's own series into the window, judged in the
  rule's direction, wherever the read tier can follow the rule's definition.
- A rule whose series cannot be read disproves nothing.
- `output-quality-degradation` is a mode, staged end to end: scenario, e2e case,
  recording, graded fix, eval case.

**Non-Goals:**
- Rules Argus cannot follow: math expressions between query and threshold, several
  queries, range evaluators (`within_range`, `outside_range`), non-Prometheus
  datasources. They resolve to no series, which is safe (no disproof) rather than
  wrong.
- Per-signal thresholds. The rule's series is judged against the same
  baseline-relative bar as the five; the rule's own threshold is the operator's, and
  using it would duplicate the alerting tool (spec §9).
- FM-33, accelerator heterogeneity.
- A paid eval run. The eval case lands at `UNMEASURED`, as every new case does.

## Decisions

### D1. The read tier owns rule-to-series resolution
`get_metrics_summary` gains an optional `rule` (the uid the alert carried). The read
server reads the rule's definition, resolves its query and direction, and asks the
metrics source for that query beside the fixed ones. No PromQL crosses into an agent;
agents pass the uid they already hold. *Alternative:* the Investigator reads the rule
and passes PromQL down - rejected, it puts Grafana's shape and a query language in an
agent.

### D2. Resolution follows the `condition` chain
From the definition's `condition` refId: a `threshold` expression gives
`conditions[0].evaluator.type` and its `expression` input; a `reduce` expression
gives its `expression` input; a `classic_conditions` expression gives
`conditions[0].evaluator.type` and `conditions[0].query.params[0]`. The chain must end
at exactly one data query (a `data[]` entry that is not an expression) with a
`model.expr`. `gt`/`gte` read as worse above, `lt`/`lte` as worse below; any other
evaluator, a `math` step, or a second query resolves to none. Field names are
Grafana's, verified against `pkg/expr/threshold.go` (evaluator `type`, `params`) and
the provisioning API's rule shape (`condition`, `data[].model.expr`,
`keep_firing_for`). Wire names are named `Final` constants in `alert_rules.py`.

### D3. The bucket carries a `RuleReading`
`MetricBucket.rule_reading: RuleReading | None = None`, and `RuleReading` is a
contract in `argus_core.models` with `value: float` and `worse_when:
Literal["above", "below"]`. The direction rides on every minute so that every
consumer of a window - the onset, the recovery, the gate, the postmortem - can judge
it without a second argument threaded through `find_onset`'s many callers.
*Alternative:* a window object wrapping the buckets - rejected, it changes the
type every channel, event and repository carries.

### D4. The adapter takes one additional query
`MetricsSource` gains an optional additional query. The adapter queries it like the
fixed ones and sets the value on each minute it answers for. A `bad_data` refusal or
an empty answer leaves `rule_reading` unset on every minute and does not fail the
window (`MetricsUnavailable` stays reserved for the fixed fields).

### D5. Judging: a sixth series, oriented
`anomaly` builds the judged series as the five plus the rule reading where the window
carries one, negating its values when it is worse below, so the existing
"value above the bar departs" rule, baseline, spread and persistence all apply
unchanged. A minute without a rule value contributes nothing to that series' baseline
and is not departed in it. `THE_JUDGED_SIGNALS` becomes the signals a given window
was judged on, so a disproof names `rule_reading` where it was judged.

### D6. The disproof guard
`investigation.py` disproves only if, where `alert.rule` is set, at least one minute
carries a rule reading. Otherwise it proceeds as for an alarm a flat window cannot
contradict: anchored on the measured onset if the five show one, else on the minute
the alarm fired.

### D7. Every metrics read passes the rule
The Investigator's `metrics_over`, Mitigation's `recent_metrics_over` (which already
receives the rule on the rule path) and the Postmortem's metrics source all pass the
rule, so the onset, the recovery minute and the postmortem's figures are read off the
same series. The rule-judged verdict (alert-decided-verification) is unchanged; the
recovery it records is now dated on the series that paged.

### D8. What the model sees
The Investigator's minute rows show the rule reading's value as a `rule_reading`
column; the prompt says once which rule paged on it, by its uid, and which way is worse.
The query stays in the read tier: it is the metrics backend's language, and nothing
past the port speaks it.
The `get_metrics` tool description names the column. This changes the eval
configuration digest, so pooled samples stop counting - every bar is already stale.

### D9. The mode
`FailureMode.OUTPUT_QUALITY_DEGRADATION = "output-quality-degradation"`, its
`meaning()` separating it from `bad-deployment` (requests fail or slow) by which
signal moved. `DEFAULT_STRATEGIES` maps it to `RollBackDeploymentStrategy`, the
many-to-one precedent the rollback spec states.

### D10. The shop's categoriser
- `io_shop/categorising.py`: a purchase title is derived from its price with no
  random draw (so every recorded figure stays put), and categorised by a model:
  v1 looks titles up in a lowercase vocabulary; v2 is the upgrade whose
  vocabulary is tokenised differently and is served the raw title - a
  training/serving mismatch - so most titles match nothing and are filed under
  "General" with no confidence. The model version comes from
  `deploy/values-production.yaml` (`categoriser.model`), which on `main` names v2:
  the fault is on `main`, uncovered by `tests/io_shop`.
- The generator gains a deploy-shaped condition (`ModelUpgrade`) whose
  `share_of(minute)` mixes v1's and v2's confident share across the onset; no new
  random draw.
- `categoriser_confident_ratio` is a gauge in the exposition and a bucket field;
  the Prometheus stand-in answers `avg(categoriser_confident_ratio)`.
- Rule `io-shop-categorisation-confidence-low`, alertname
  `CategorisationConfidenceLow`: reduce `mean` over 2m, `lt 0.8`, pending 5m. Two
  minutes, not five: a scenario's window freezes three clean minutes after the
  rollback lands, and a longer range would still reach the broken minutes there,
  so the rule would never read normal.
- Scenario `categoriser-model-upgraded`, family "AI-specific", a `ScenarioDeploy`
  whose revision and parent sit on an unmerged `deploy/categoriser-model-v2`
  branch, a log line at the onset naming the model loaded, a console entry.

### D11. The stand-in's rule definitions carry PromQL
Every series rule's `model.expr` becomes the PromQL its Prometheus stand-in answers,
replacing the bucket field name it carries today; the memory rule's ratio gets a
query of its own (`max(max_over_time(process_resident_memory_bytes[1m])) /
max(container_spec_memory_limit_bytes)`), answered by the stand-in. The threshold
expression's evaluator carries `gt` or `lt` per rule. Consequence: every series-rule
incident in the suite now carries its rule's series - mostly a duplicate of a fixed
signal - and its onsets are found over six series. The full free replay is the check.

### D12. End to end
`tests/e2e/test_a_categoriser_upgrade_is_rolled_back.py` posts the Grafana payload
naming the staged rule (`_naming_the_staged_rule`), and asserts relations Argus
holds: the cause is `output-quality-degradation`, the onset Argus published falls at
the minute the rule's series departed, the last action is a rollback that the rule
confirmed, the incident ends `mitigated`, a fix was proposed. `both` only, like the
undated finding; a `record_incident.py` entry; added to
`THE_RECORDINGS_THAT_MUST_CARRY_A_FIX`; a free rehearsal borrowed from
`both-bad-deployment` before the paid capture.

## Risks / Trade-offs

- **Every series incident gains a sixth judged series** → an onset could move a
  minute where the rule's series departs before the fixed signal it duplicates.
  Mitigated by the full free replay before anything is recorded; a moved onset is a
  finding, not something to paper over.
- **Grafana's `condition` shapes are many** → only the two common ones are followed;
  everything else resolves to no series, which forgoes the disproof rather than
  risking a false one.
- **The direction rides on every minute** → redundant per row. Accepted for not
  threading a parameter through every `find_onset` caller.
- **Prompt and tool description change** → eval pools reset; replay recordings still
  replay (the double serves in order).
- **The paid recording** → one `both` walk, about $1-2 at the last capture's rate;
  asked for explicitly when everything free is green.

## Migration Plan

No schema change: `MetricBucket` is carried in events as JSON and the new field is
optional, so stored events without it read as before. Deploy order is free - the
read tier ignores a missing `rule`, and an older agent omits it.

## Open Questions

None. The user settled detection (rule's query), direction (falling share, read from
the rule), the change (deployed upgrade) and the postmortem figure (reported).
