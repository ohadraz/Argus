## Why

`get_log_lines` currently returns the Target Service's entire log, unfiltered -
the exact "full dump" spec §16 exists to avoid. The two-phase retrieval it
describes (cheap aggregated metrics first, raw log lines only for the buckets
that look anomalous) can't be built yet because the first phase has no tool and
the second has nothing to scope by: log entries carry no timestamps, so there
is nothing to window on.

This change adds the missing first phase and makes the second real, which is
what unblocks the Investigator's ReAct loop - the loop's fixed opening steps
(§9) are exactly "query the metrics summary, then drill into the anomalous
slice."

## What Changes

- **Target Service** (`Argus-Demo-Target-App`): log entries gain timestamps,
  and a new `GET /metrics` endpoint returns per-minute pre-aggregated buckets
  (error rate, p50/p95 latency, request volume) for the active scenario -
  matching the `/logs` shape: dumb, unfiltered, no query params. Both
  pre-seeded scenarios get bucket data whose anomalous minutes line up with
  their existing log entries.
- **`argus-read-mcp`** gains `get_metrics_summary`, returning the windowed
  per-minute buckets.
- **`get_log_lines(alert_time, window_start, window_end, filters, bucket_ids)`**
  stops being a pass-through: it derives the retrieval window from the alert
  time and the configured lookback/lookahead, applies it, and scopes by
  optional `bucket_ids` - the windowing/filtering §16 assigns to the server
  rather than the adapter. An explicit window overrides the derived one, but
  is clamped to a configured maximum span.
- **`read_mcp_client`** gains a typed `get_metrics_summary`, and
  `get_log_lines` gains the `alert_time` and `bucket_ids` parameters.
- **Config** gains the §16 knobs: lookback `X`, lookahead `Y_max`, and the
  maximum window span an explicit override may request.

## Capabilities

### New Capabilities
- `two-phase-retrieval`: windowed, aggregated-then-scoped retrieval of metrics
  and logs - `get_metrics_summary` plus a `get_log_lines` that actually
  derives its window from the alert time, windows, and scopes by bucket.

### Modified Capabilities
- `read-mcp-server`: `get_log_lines` gains real windowing and filtering
  behavior and `alert_time`/`bucket_ids` parameters, replacing the
  pass-through that returned the full log.
- `target-service-scenario-control`: scenario log entries carry timestamps,
  and each scenario also serves per-minute metric buckets via `GET /metrics`.

## Impact

- Modified (separate repo): `Argus-Demo-Target-App` - timestamped log entries,
  new `GET /metrics` endpoint, per-scenario bucket fixtures.
- Modified: `modules/read_mcp_server/` (new tool + real windowing logic),
  `modules/read_mcp_client/` (typed `get_metrics_summary`, `alert_time`,
  `bucket_ids`), `modules/argus_core/src/argus_core/config.py`
  (lookback/lookahead/max window span).
- `agent_investigator` is unaffected for now - it keeps calling
  `get_log_lines()` with no window. The ReAct change is what starts driving
  both phases; this change makes the tools exist and behave correctly.
- Existing e2e tests must keep passing: timestamped log lines still contain
  the keywords `_determine_cause` matches on.
