## 1. The shop's categoriser and scenario (Argus-Demo-Target-App; code first, tests after)

- [x] 1.1 `io_shop/categorising.py`: titles derived from price with no random draw; model v1 (lowercase vocabulary) and v2 (the mismatched tokenisation, served the raw title); the version read from `deploy/values-production.yaml` `categoriser.model`, `v2` on `main`
- [x] 1.2 Generator: a `ModelUpgrade` condition mixing v1's and v2's confident share across the onset with no new random draw; `categoriser_confident_ratio` on `GeneratedMinute`, the demo's `MetricBucket` and `_the_buckets`
- [x] 1.3 Exposition gauge `categoriser_confident_ratio`; Prometheus stand-in answers `avg(categoriser_confident_ratio)` and the memory rule's ratio query
- [x] 1.4 Grafana stand-in: every series rule's definition carries its PromQL as `model.expr` and its comparator as the evaluator `type`; `lt` rules evaluate below the threshold; rule `io-shop-categorisation-confidence-low` (`CategorisationConfidenceLow`, mean over 5m, `lt 0.8`, pending 5m)
- [x] 1.5 Scenario `categoriser-model-upgraded`: family "AI-specific", `ScenarioDeploy` on an unmerged `deploy/categoriser-model-v2` branch (parent v1, revision v2), seeding, `generated_window`/`phase` branches, rollback ends the stretch, a log line at the onset, `_WHAT_FIRED` entry, console entry
- [x] 1.6 Demo tests: categoriser v1/v2 behaviour, the series falls and nothing else moves, the rule fires and resolves on rollback, definitions' queries are answered by the stand-in, `tests/io_shop` green on `main` with the fault uncovered
- [x] 1.7 Commit the demo app, push it and the `deploy/categoriser-model-v2` branch (PowerShell)

## 2. The kernel (argus_core)

- [x] 2.1 Test first: `RuleReading` (`value`, `worse_when`) and `MetricBucket.rule_reading` default `None`
- [x] 2.2 Implement `RuleReading` in `argus_core.models` and the bucket field
- [x] 2.3 Test first: `FailureMode.OUTPUT_QUALITY_DEGRADATION` has a meaning that separates it from `bad-deployment`
- [x] 2.4 Implement the mode, its maintainer comment and its meaning
- [x] 2.5 Test first (`test_anomaly.py`): an onset only the rule's series shows; a worse-below series that rises does not depart; recovery waits for the rule's series; a window without it is judged on the five exactly as before; the judged signals a window names include `rule_reading` only where it was judged
- [x] 2.6 Implement the oriented sixth series in `anomaly` and the per-window judged signals

## 3. Reading the rule's series (metrics_source, read tier)

- [x] 3.1 Test first (`test_prometheus_adapter.py`): an additional query's values ride on the buckets; a refused or empty additional query leaves the fixed window intact
- [x] 3.2 Implement the additional query in the adapter and the `MetricsSource` port
- [x] 3.3 Test first (`read_mcp_server` `test_alert_rules.py`): a threshold chain resolves query and direction; a classic condition resolves; `gte`/`lte`; a math step, two queries, a range evaluator, no `expr` each resolve to none
- [x] 3.4 Implement the resolution with Grafana's wire names as public `Final` constants
- [x] 3.5 Test first (`read_mcp_server` retrieval/server): `get_metrics_summary` with a rule carries its readings; with no rule, or an unresolvable one, carries none
- [x] 3.6 Implement the `rule` parameter in the server tool, the retrieval function and the typed client

## 4. The walk

- [x] 4.1 Test first (`agent_investigator`): the rule is passed to the metrics read; an alarm whose rule's series is unreadable is not disproven; a disproof names `rule_reading` where it was judged; the minute rows carry the column and the prompt names the rule and direction
- [x] 4.2 Implement in `retrieval.py`, `investigation.py`, `tools/metrics.py`
- [x] 4.3 Test first (`agent_mitigation`): `recent_metrics_over` passes the rule; `take_action` re-reads the service for the rule (the recovery minute's dating on the rule's series is `find_recovery`'s, tested in 2.5); `output-quality-degradation` maps to the rollback strategy
- [x] 4.4 Implement
- [x] 4.5 Test first: the evidence carries the alert's rule (`orchestrator` gathering); `measure` reads the metrics for it (`agent_postmortem`); the real metrics source passes it to the read tier (`orchestrator` sources)
- [x] 4.6 Implement `IncidentEvidence.rule`, the `Metrics` port's rule, `gathering.py`, `orchestrator/sources.py`

## 5. What a reader sees

- [x] 5.1 Test first (`agent_postmortem`): the rule series' baseline, mean while broken and worst; none reported where the window carries none
- [x] 5.2 Implement the figure and its prompt line
- [x] 5.3 Test first (`argus_narration`, `argus_web`): the column is shown where present and absent otherwise
- [x] 5.4 Implement `BucketRow` and `evidence.html`

## 6. Contracts and evals

- [x] 6.1 Propose the Prometheus contract test's new queries (`avg(categoriser_confident_ratio)`, the memory ratio) against a real Prometheus scraping the shop
- [x] 6.2 Propose the eval case `output-quality-degradation-is-told-from-a-bad-deployment`, bar `UNMEASURED`, with its incident builder

## 7. End to end

- [x] 7.1 Propose `RECORDED_OUTPUT_QUALITY_DEGRADATION`, its entry in `THE_RECORDINGS_THAT_MUST_CARRY_A_FIX`, and the e2e case
- [x] 7.2 `record_incident.py` entry; `noxfile` leaves the case to `both`; a rehearsal rewrite in `seed_a_rehearsal.py` (from `both-bad-deployment`: the mode named, the fix submitted)
- [x] 7.3 Rehearse the case alone, free; then the full `e2e_replay(mode='both')`, free
- [x] 7.4 Ask for the paid `record(mode='both')`; record; remove the rehearsal set first
- [x] 7.5 Replay the case from the real recording; `grade_fixes`; report the spend

## 8. Docs

- [x] 8.1 Spec: §9/§10 (the disproof guard and its grounds), §12/§12.1 (the rule's query and comparator are read), §16 (the rule's series in the metrics channel and among the judged signals), §21 (the postmortem figure)
- [x] 8.2 Backlog: FM-17 built (scenario, what moved, what it added, near-miss, mitigated and not resolved), the AI-specific family row

## 9. Review before commit

- [x] 9.1 lint, typecheck, guard_layering, test_all, integration, contract, full e2e_replay
- [x] 9.2 Comments, docstrings, jargon, docs aligned; no missing, redundant or weak tests
- [ ] 9.3 Commit the demo app and Argus (one line each, approved); archive the change
