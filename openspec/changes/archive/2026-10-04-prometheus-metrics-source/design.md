## Context

`read_mcp_server/retrieval.py` fetches `GET {target_service_url}/metrics` (the
demo app's invented JSON rows, all 360 minutes) and filters by window itself.
Its consumers (investigator, mitigation's verification, the postmortem's cost
estimate through the orchestrator) all receive `list[MetricBucket]` from
`get_metrics_summary` and are untouched by this change.

Every other provider is already read this way: a settings slice naming a base
URL, a port in Argus's vocabulary, one adapter that knows the vendor, and the
demo app standing in for the vendor at `/<vendor>/<vendor's real path>`
(`revenue_source` + Stripe is the model to copy).

## Goals / Non-Goals

**Goals:**
- Argus speaks Prometheus's real range-query API; nothing above the adapter
  knows it.
- The demo app answers that API with the same numbers it serves today, so no
  recording, scenario or anomaly rule moves.

**Non-Goals:**
- A real Prometheus in the stack. Scraping records only the present; every
  scenario starts with six hours of history and some windows freeze after
  mitigation. Feeding that into a real TSDB means backfilling on seed and
  deleting series on reset - a new class of flake for no gain to what the
  e2e suite proves.
- A PromQL engine in the demo app. It recognises Argus's queries verbatim.
- The contract test against a real Prometheus - a follow-up.

## Decisions

**Module `metrics_source`, port as a `Protocol`.** `minutes.py` holds
`MetricsSettings` (`prometheus_base_url`), `MetricsSource`
(`__call__(start, end) -> list[MetricBucket]`) and `MetricsUnavailable`;
`prometheus_adapter.py` holds the adapter and is the only file naming
Prometheus. A Protocol rather than the `Callable` alias `revenue_source` uses,
because the user asked for one and `create_autospec` stands it in cleanly.
`MetricBucket` stays in `argus_core.models` - it is already a contract.

**Plain `httpx2`, no client library.** Prometheus publishes no official Python
client for its query API; the request is four parameters. The HTTP call is
injected (as `client_of` is in the Stripe adapter) so the adapter's unit tests
need no network.

**One query per field, idiomatic names.** The adapter owns a `Final` constant
per field, e.g. error rate as
`sum(rate(http_requests_total{code=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))`,
p95 as `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[1m]))) * 1000`,
memory as `max_over_time(process_resident_memory_bytes[1m])`. Exact strings
are settled at implementation; the demo app imports nothing from Argus, so it
holds its own copy and the stand-in's tests pin them. Twelve round trips per
read, locally - accepted over one regex query that a real Prometheus would
answer with differently-labelled series.

**Timestamps follow Prometheus.** A sample at `t` describes `[t - 1m, t]`, so
the adapter queries minute-aligned steps and maps each sample to
`bucket_id = t - 60s`; the stand-in serves each minute at its end. The
consequence: a real Prometheus may not report the in-progress minute until it
completes, where today's JSON includes it partially - which is what the
reporting lag below is for.

**The reporting lag is a setting: 1 by default, 0 on every push, 1 nightly.**
Task 1.1 showed that a source reporting each minute only once it ends makes
mitigation's recovery wait run out before the first whole post-action minute
arrives, and refutes a rollback that worked. So `metrics_reporting_lag_minutes`
(default 1, a real Prometheus) extends that deadline
(`_when_a_recovery_would_have_shown` in `agent_mitigation/trying.py`) by the
lag. The stand-in has the matching setting: at 0 it also serves the unfinished
minute, as `/metrics` does today, so `e2e_replay` on every push runs as fast as
now; at 1 it does not, and the nightly runs the suite that way. Measured cost
of lag 1: about 18 minutes on a 28-minute run. Alternative rejected: a shared
fake clock for the whole stack - right, but a change of its own.

The adapter's `end` is rounded up to the next minute boundary, so the step at
the unfinished minute's end is asked for whatever the lag; a source that
cannot answer it simply returns no sample there.

**Ints round-trip.** Prometheus values are strings of floats; the adapter
rounds the integer fields. The stand-in emits the exact values it holds, so
nothing drifts.

**A missing required series drops the minute; a missing optional one is
`None`.** That is what the blind-spot scenario needs (its unpublished minutes
have no row today) and what `memory_limit_bytes` / `cpu_limit_cores` /
`cache_hit_ratio` already mean.

**No window means the configured span up to now.** `query_range` needs both
bounds; `[now - metrics_window_minutes, now]` (360) is what mitigation's
unanchored read gets today, since the demo app's span is also 360.

**Failure is `MetricsUnavailable`.** Transport errors, non-2xx, and
`"status": "error"` all become it; `read_mcp_server` lets it fail the tool
call, as an HTTP error does today.

**Demo app routes.** `/prometheus/api/v1/query_range` (stand-in),
`/metrics` (text exposition of the latest values, for a future scrape and the
follow-up contract test), `/scenario/metrics` (the old JSON, beside the other
`/scenario/*` controls).

## Risks / Trade-offs

- [The stand-in can drift from real Prometheus] → the follow-up contract test
  in `tests/contract/prometheus/`.
- [The push-time e2e no longer exercises lag 1] → the nightly does, and the
  deadline arithmetic is unit-tested at both values.
- [e2e tests read `GET /metrics` directly] → the user moves them to
  `GET /scenario/metrics` in the same change; the demo app change lands first.

## Open Questions

- Settled: does anything depend on the partial, in-progress minute?
  **Task 1.1 result: it does.** With the in-progress minute dropped, the
  bad-deployment case (40/40 the run before) failed: its rollback at
  18:38:07 was polled until 18:40:00, judged not to have helped, and undone,
  exactly as the first whole post-rollback minute (18:39) would have
  arrived (ledger `.claude/local/runs/2026-10-04_183758.md`, 39/40). Answered
  by the reporting-lag setting above.
