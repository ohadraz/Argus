## 1. Target Service: timestamps and metrics (Argus-Demo-Target-App repo)

- [x] 1.1 Restructure each scenario fixture so log entries and metric buckets
      derive from one per-scenario structure (avoids the two drifting apart),
      with per-entry minute offsets
- [x] 1.2 Record the seed instant in `POST /scenario/seed`; clear it in
      `POST /scenario/reset`
- [x] 1.3 Make `GET /logs` prefix each entry with a timestamp derived from the
      seed instant plus that entry's offset
- [x] 1.4 Add `GET /metrics` returning the active scenario's per-minute buckets
      (minute, error rate, p50, p95, volume), empty list when no scenario is
      active
- [x] 1.5 Author bucket values so `feature-flag-toggle` shows an error-rate
      spike after the toggle and `bad-deployment` a p95 spike after the deploy

## 2. Config

- [x] 2.1 Add the lookback, lookahead and maximum-window-span settings to
      `argus_core.config` (defaults: 30 minutes back, 10 minutes forward)

## 3. read_mcp_server: windowing

- [x] 3.1 Add timestamp parsing for a log line, and minute-bucket derivation
      from a parsed timestamp
- [x] 3.2 Add window resolution: derive `[T0 - X, T0 + Y_max]` from an alert
      time and the configured bounds, let an explicit `window_start`/
      `window_end` override it, and clamp any window to the configured maximum
      span
- [x] 3.3 Extend `get_log_lines` with `alert_time`/`window_start`/`window_end`/
      `bucket_ids` (ISO-8601 strings, all optional) and apply the resolved
      window and bucket scoping; omitting all of them preserves current
      behavior. A clamped span is reported, not raised
- [x] 3.4 Propose unit tests for window derivation, explicit-window precedence,
      clamping, bucket scoping, and the no-args passthrough (per `tests/` TDD
      policy - proposed in chat)

## 4. read_mcp_server: get_metrics_summary

- [x] 4.1 Add a bucket model to `argus_core` shared models (both the server and
      the typed client need it)
- [x] 4.2 Implement `get_metrics_summary(alert_time, window_start, window_end)`
      as an `@mcp.tool()`, fetching `GET /metrics` and applying the same
      resolved window as `get_log_lines` - with the fetch injection seam on a
      private helper, per `read-mcp-server`'s `Callable`-default constraint
- [x] 4.3 Propose unit tests for bucket windowing and the empty-scenario case

## 5. read_mcp_client

- [x] 5.1 Add typed `get_metrics_summary(alert_time, window_start, window_end)`
      returning the bucket model
- [x] 5.2 Extend typed `get_log_lines` with `alert_time` and `bucket_ids`
- [x] 5.3 Propose an integration test driving both phases against a real
      server and a stub Target Service: summary first, then log lines scoped to
      bucket ids from that summary

## 6. Verification

- [x] 6.1 `nox -s lint`
- [x] 6.2 `nox -s typecheck`
- [x] 6.3 `nox -s test_all`
- [x] 6.4 `nox -s guard_e2e_boundary`
- [x] 6.5 `nox -s e2e` - existing investigator e2e must still pass unchanged,
      confirming timestamped lines don't break `_determine_cause`'s keyword
      matching
