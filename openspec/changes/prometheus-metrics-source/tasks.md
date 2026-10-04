## 1. Settle the open question for free

- [x] 1.1 Establish whether any consumer depends on the in-progress minute: run `e2e_replay(mode='both')` with the demo app's `/metrics` temporarily dropping its last, partial row; record the result in design.md and revert

## 2. Demo app (Argus-Demo-Target-App)

- [x] 2.1 Move the per-minute JSON rows from `GET /metrics` to `GET /scenario/metrics`; update `console.py` and the demo app's own tests
- [x] 2.2 Serve `GET /prometheus/api/v1/query_range` for Argus's fixed queries, in Prometheus's envelope, from the same minutes; unpublished minutes have no sample
- [x] 2.3 Answer an unknown query with 400 `bad_data`, and no active scenario with an empty matrix
- [x] 2.3a Reporting lag setting (0 or 1, default 0 until the nightly sets 1): at 0 serve the unfinished minute at the step it ends on, at 1 withhold it
- [x] 2.4 Serve `GET /metrics` as text exposition (`text/plain; version=0.0.4`) of the latest values
- [x] 2.5 Tests pinning each query's samples to the JSON rows, value for value
- [ ] 2.6 Commit and push the demo app

## 3. metrics_source module (TDD - tests proposed in chat)

- [x] 3.1 Scaffold `modules/metrics_source` (new-module skill); add to `root_packages` and the right layering contract
- [x] 3.2 `minutes.py`: `MetricsSettings`, `MetricsSource` protocol, `MetricsUnavailable`
- [x] 3.3 `prometheus_adapter.py`: request shape (path, `query`, `start`, `end`, `step=60s`)
- [x] 3.4 Translation: matrix to buckets, `bucket_id = t - 60s`, ints rounded, missing required series drops the minute, missing optional is `None`
- [x] 3.4a The adapter's `end` is rounded up to the end of its minute
- [x] 3.5 Failures: transport, non-2xx and `"status": "error"` raise `MetricsUnavailable`

## 4. Wiring

- [x] 4.1 `prometheus_base_url` in `argus_core/config.py` (default `http://localhost:8080/prometheus`) and `.env.example`
- [x] 4.2 `read_mcp_server`: `get_metrics_summary` asks the source for the resolved window; no window means the last `metrics_window_minutes` up to now; remove `target_service_metrics`
- [x] 4.2a `metrics_reporting_lag_minutes` (default 1) extends `_when_a_recovery_would_have_shown`'s deadline in `agent_mitigation/trying.py`; 0 in the push-time e2e stack
- [x] 4.2b Nightly runs `e2e_replay` with the lag at 1 on both sides (Argus and the stand-in)
- [x] 4.3 `read_mcp_client` suite's fake Target Service serves the Prometheus stand-in path (propose in chat)

## 5. Tests outside Claude's reach (propose whole files in chat)

- [x] 5.1 `tests/e2e/framework/world.py`, `flags.py` and the e2e tests reading `GET /metrics` switch to `GET /scenario/metrics`

## 6. Verify and close

- [x] 6.1 lint, typecheck, guard_layering green; affected module suites green
- [x] 6.2 `e2e_replay(mode='both')` green with no re-record
- [ ] 6.3 Rename `GET /metrics` to `GET /scenario/metrics` in `flag-driven-telemetry` and `monitoring-blind-spot-scenario` specs at sync
- [ ] 6.4 Note the follow-up: contract test against a real Prometheus in `tests/contract/prometheus/`
