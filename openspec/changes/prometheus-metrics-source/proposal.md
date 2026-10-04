## Why

Argus reads the Target Service's metrics from a JSON shape the demo app
invented (`GET /metrics`, a list of per-minute rows), which no real metrics
backend answers with. A deployment watching a real service would have
Prometheus in front of it, so the read tier has to speak Prometheus's query
API - and, like every other provider Argus reads (flags, payments, on-call,
pay bands, deploys), reach it through a port with the vendor confined to one
adapter, aimed by a base-URL setting.

## What Changes

- New module `metrics_source`: a `MetricsSource` protocol (the port - minute
  buckets between two instants, in Argus's `MetricBucket`), a
  `MetricsUnavailable` error, a `MetricsSettings` slice, and
  `prometheus_adapter.py`, the one place Prometheus is known by name. The
  adapter sends `GET {prometheus_base_url}/api/v1/query_range` with real
  PromQL, one query per bucket field, `step=60s`, and translates the `matrix`
  answers into `MetricBucket`s.
- New setting `prometheus_base_url`, default
  `http://localhost:8080/prometheus` - the same prefix pattern as
  `STRIPE_BASE_URL` and `HR_BASE_URL`: the URL is the setting's, the path
  after it is the vendor's real one.
- `read_mcp_server` reads metrics through the port and asks the source for the
  window, instead of fetching every minute and filtering. A call with no window
  asks for the last `metrics_window_minutes` up to now.
- Demo app (`Argus-Demo-Target-App`):
  - Serves Prometheus's query API at `/prometheus/api/v1/query_range`, answering
    Argus's fixed set of PromQL queries from the same generated minutes, in
    Prometheus's own envelope, including its error envelope for a query it does
    not know.
  - **BREAKING**: `GET /metrics` becomes Prometheus text exposition format: the
    current values of the series those queries name.
  - **BREAKING**: the per-minute JSON rows move to `GET /scenario/metrics`, for
    the console and the e2e suite.
- What the model is shown does not change, value for value, so no recording is
  re-made.

Out of scope, as a follow-up: a contract test against a real Prometheus in
`tests/contract/prometheus/`, proving the adapter's PromQL parses and its
answers have the shape the stand-in gives.

## Capabilities

### New Capabilities
- `metrics-source`: the port Argus reads a service's minute buckets through,
  and the Prometheus adapter behind it.
- `target-service-prometheus-api`: the demo app's stand-in for Prometheus's
  range-query API and its text exposition endpoint.

### Modified Capabilities
- `two-phase-retrieval`: `get_metrics_summary` reads through the metrics
  source, and a call with no window returns the last configured span rather
  than everything the service holds.
- `target-service-scenario-control`: the per-minute JSON rows are served at
  `GET /scenario/metrics`; `GET /metrics` is Prometheus's.

## Impact

- New module `modules/metrics_source` (joins `root_packages` in import-linter).
- `read_mcp_server`: `retrieval.py`, `server.py`; depends on `metrics_source`.
- `argus_core/config.py`, `.env.example`: `prometheus_base_url`.
- Demo app: `app.py`, `console.py`, its own tests.
- Argus `tests/e2e/framework/world.py`, `flags.py` and the e2e tests that read
  `GET /metrics` directly: switch to `GET /scenario/metrics` (user's edit).
- Other specs that name `GET /metrics` (`flag-driven-telemetry`,
  `monitoring-blind-spot-scenario`) mean the JSON rows and are renamed at sync.
