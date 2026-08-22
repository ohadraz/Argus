## Context

`read_mcp_server.get_log_lines` accepts `window`/`filters` but acts on
neither - it returns the Target Service's whole log, deliberately deferred in
`read-mcp-server`'s design.md because "no caller can supply a meaningful value
for either until the metrics tool and the ReAct loop exist to drive them."

This change builds the metrics half, so both become drivable. Two facts
constrain it:

- **Log entries have no timestamps.** They are plain strings
  (`"ERROR target-service: request failed - ..."`). Nothing can be windowed
  until that changes, so timestamping the fixture is a prerequisite, not a
  nice-to-have.
- **The Target Service serves no metrics.** It has `/health`, `/scenario/*`
  and `/logs`. Per §15.1 it is the stand-in for infrastructure Argus doesn't
  actually run, so metrics arrive the same way logs did: as an endpoint on the
  fixture, not a real observability stack.

Note that metrics serve a different purpose here than the alert that starts an
incident. The alert (§25) reports *that* something is wrong - one threshold
crossing. The metrics summary reports its *shape*: when it started, which
minutes are anomalous, whether error rate or latency moved, and against what
baseline. That shape is what lets the Investigator scope its log retrieval
instead of dumping everything.

## Goals / Non-Goals

**Goals:**
- Give `argus-read-mcp` a `get_metrics_summary(window)` tool returning
  per-minute pre-aggregated buckets.
- Make `get_log_lines` genuinely window, bound that window in time, and scope
  by `bucket_ids` - the server-side responsibility §16 assigns it.
- Timestamp the Target Service's scenario logs and serve matching per-minute
  metric buckets, so the two phases line up on real scenario data.

**Non-Goals:**
- Any real observability stack - no Prometheus, no OTel Collector, no
  instrumentation. The Target Service simulates this infrastructure by
  design (§15.1), exactly as it already does for logs.
- Iterative widening. The server derives and enforces the window; *deciding*
  to re-fetch a wider one after seeing that the anomaly starts at the window's
  left edge is the ReAct loop's job, in its own change.
- The ReAct loop itself, and any change to `agent_investigator`, which keeps
  calling `get_log_lines()` with no alert time and no window.

## Decisions

**A dumb `GET /metrics` on the Target Service, mirroring `GET /logs`.** No
params, returns the active scenario's full bucket list; the server does all
windowing. This is the same ports-and-adapters split §16 already mandates for
logs ("the port only guarantees 'return the log'"), and keeps the fixture
consistent with itself.

**Scenario timestamps are anchored to seed time, not baked in as absolute
literals.** A fixture with hardcoded absolute timestamps would drift into the
distant past, and any window around a freshly-fired alert would correctly
exclude every line - the scenario would silently stop working. So
`POST /scenario/seed` records the seed instant, and both `/logs` and
`/metrics` derive entry timestamps as fixed offsets from it (e.g. entry *n* at
seed + *n* minutes). Deterministic per seed, always "recent", and the two
endpoints stay aligned because they derive from the same anchor.

**A bucket is one minute, identified by its minute-truncated ISO-8601
timestamp.** `bucket_ids` is then a list of those strings - human-readable in
a ReAct transcript, directly comparable to a log line's own timestamp, and no
separate id scheme to keep in sync.

**Times cross the tool boundary as ISO-8601 strings (`alert_time`,
`window_start`, `window_end`), all optional.** Every `@mcp.tool()` parameter
must be JSON-schema-representable (the `read-mcp-server` change already hit
this with `Callable` defaults), which rules out passing a `datetime` pair or a
custom object. Omitting all three means "no window" - preserving today's
behavior for `agent_investigator`, which is not part of this change.

**The window is bounded in time, not by line count, and the server derives it
from the alert time.** Given `alert_time` = `T0`, the window is §16's
`[T0 - X, T0 + Y_max]`, with `X` and `Y_max` config values (default 30 and 10
minutes). Bounding by line count instead was considered and rejected: a cap of
*N* lines is a bound on response size that says nothing about *which* stretch
of the incident you got, so the same call returns a different slice of history
as log volume changes - unusable as the basis for a reproducible benchmark
scenario, and it silently drops exactly the oldest lines that explain onset.

**An explicit `window_start`/`window_end` overrides the derived window but is
clamped to a configured maximum span.** The override exists so a caller that
has already learned something - the ReAct loop widening after seeing an
anomaly at its window's edge - can act on it. The clamp exists so that
widening cannot degenerate into "dump everything," which is the failure mode
§16 exists to prevent. A clamped request returns the clamped window's data and
says the span was clamped, rather than raising: a reasoning caller can act on
that, an exception just loses the call.

**The window is not chosen per alert type.** A model picking "45 minutes for a
CPU alert, 10 for an error-rate alert" produces plausible numbers but not
reproducible ones, and a too-narrow guess fails silently - it finds nothing and
reports no cause, which is indistinguishable from a correct negative. A fixed
configured default plus evidence-driven widening gives the same adaptivity
without either problem.

**Log parsing lives in the server, not the fixture format.** The server
extracts a leading timestamp from each line to window it. That keeps the port
contract unchanged ("return the log lines") and means a future filesystem or
S3 adapter needs no windowing logic of its own.

## Risks / Trade-offs

- **Timestamping changes the log line format that `_determine_cause` matches
  on.** Its keyword matching (`"feature flag"`, `"toggled"`, `"error"`) is
  substring-based and case-insensitive, so a prefixed timestamp shouldn't
  break it - but the existing e2e and unit tests are the check, and must pass
  unchanged.
- **Seed-anchored timestamps make `/logs` output depend on when it was
  seeded.** Repeated calls after one seed stay identical (anchored at seed,
  not now), so this remains deterministic - but a test asserting on absolute
  timestamps would be fragile. Tests should assert on relative ordering and
  windowing behavior instead.
- **Bucket data is hand-authored to match the log entries.** If someone edits
  one scenario's logs without its buckets, the two phases disagree and the
  drill-down points at the wrong minute. Mitigation: derive both from a single
  per-scenario fixture structure rather than two independent lists.

## Migration Plan

The Target Service change ships first (it is a separate repo, and the server
change depends on timestamped logs existing). Both `/logs` and `/metrics`
remain unauthenticated, param-free GETs, so no compatibility shim is needed -
`get_log_lines()` with no window keeps returning everything, exactly as
`agent_investigator` expects today.

## Open Questions

None outstanding - the Target Service simulates the metrics source, consistent
with how it already simulates logs (§15.1).
