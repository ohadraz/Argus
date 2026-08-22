## ADDED Requirements

### Requirement: argus-read-mcp exposes get_metrics_summary
The system SHALL provide a
`get_metrics_summary(alert_time, window_start, window_end)` tool on
`argus-read-mcp` returning per-minute pre-aggregated buckets - each
carrying its bucket id, error rate, p50 and p95 latency, and request volume -
for the Target Service's currently active scenario.

#### Scenario: Buckets are returned for the active scenario
- **GIVEN** a scenario is active on the Target Service
- **WHEN** `get_metrics_summary` is called with no window
- **THEN** it returns that scenario's full list of per-minute buckets

#### Scenario: Buckets outside the window are excluded
- **GIVEN** a scenario is active whose buckets span several minutes
- **WHEN** `get_metrics_summary` is called with a window covering only some of
  those minutes
- **THEN** only the buckets whose minute falls inside the window are returned

#### Scenario: No active scenario yields no buckets
- **GIVEN** the Target Service has no active scenario
- **WHEN** `get_metrics_summary` is called
- **THEN** it returns an empty list

### Requirement: The metrics summary identifies anomalous minutes
The system SHALL return bucket values that distinguish anomalous minutes from
baseline ones for each pre-seeded scenario, so a caller can select which
buckets to drill into.

#### Scenario: The feature-flag-toggle scenario shows an error-rate spike
- **GIVEN** the `feature-flag-toggle` scenario is active
- **WHEN** `get_metrics_summary` is called
- **THEN** the buckets after the flag is toggled report a materially higher
  error rate than those before it

#### Scenario: The bad-deployment scenario shows a latency spike
- **GIVEN** the `bad-deployment` scenario is active
- **WHEN** `get_metrics_summary` is called
- **THEN** the buckets after the deploy report a materially higher p95 latency
  than those before it

### Requirement: Each phase derives its own window from the alert time
The system SHALL derive each phase's window from a supplied alert time `T0`,
using bounds configured separately per phase, so that a caller need only say
which incident it is asking about.

The log window SHALL be `[T0 - initial_lookback, T0 + initial_lookahead]`,
both configurable. The metrics window SHALL be one fixed configurable span
around `T0`, wider than the log window and never narrowed: the summary is what
locates the incident's onset, so a narrow metrics window can hide the very
thing the caller is looking for, and per-minute aggregates are cheap enough
that there is no reason to narrow it.

#### Scenario: The log window is derived from the alert time and configured bounds
- **GIVEN** the configured log lookback and lookahead
- **WHEN** `get_log_lines` is called with an alert time and no explicit window
- **THEN** only entries falling between the lookback before that alert time
  and the lookahead after it are returned

#### Scenario: The metrics window reaches further back than the log window
- **GIVEN** a bucket older than the configured log lookback but inside the
  configured metrics span
- **WHEN** `get_metrics_summary` is called with that alert time
- **THEN** that bucket is returned, even though a log entry of the same minute
  would fall outside `get_log_lines`' derived window

#### Scenario: Changing the configured bounds changes the derived window
- **GIVEN** a log lookback configured wider than a previously configured one
- **WHEN** the same call is made with the same alert time
- **THEN** the returned entries extend correspondingly further before the
  alert time

### Requirement: An explicit window overrides the derived one, clamped to a maximum span
The system SHALL let a caller supply an explicit `window_start`/`window_end`
in place of the derived window, and SHALL clamp any such window to that
phase's configured maximum span, reporting that the span was clamped rather
than raising, so that widening a window cannot degenerate into retrieving the
full log.

#### Scenario: An explicit window takes precedence over the alert time
- **GIVEN** an alert time and an explicit window that differ
- **WHEN** `get_log_lines` is called with both
- **THEN** the entries returned are those inside the explicit window

#### Scenario: An over-span window is clamped and reported as clamped
- **GIVEN** an explicit window whose span exceeds the configured maximum
- **WHEN** `get_log_lines` is called
- **THEN** it returns the entries inside the clamped window, and indicates
  that the requested span was clamped

### Requirement: Log retrieval is windowed and bucket-scoped
The system SHALL apply time windowing and optional `bucket_ids` scoping inside
`argus-read-mcp` when returning log lines, rather than returning the Target
Service's full log.

#### Scenario: Lines outside the window are excluded
- **GIVEN** a scenario is active whose log entries span several minutes
- **WHEN** `get_log_lines` is called with a window covering only some of those
  minutes
- **THEN** only the entries timestamped inside the window are returned

#### Scenario: bucket_ids narrows the result to those minutes
- **GIVEN** a scenario is active whose log entries span several minutes
- **WHEN** `get_log_lines` is called with `bucket_ids` naming a subset of
  those minutes
- **THEN** only entries whose minute matches one of those bucket ids are
  returned

#### Scenario: Omitting every time argument preserves unwindowed retrieval
- **GIVEN** a scenario is active
- **WHEN** `get_log_lines` is called with no alert time, no window and no
  `bucket_ids`
- **THEN** it returns the scenario's entries as before

### Requirement: The typed read client exposes both retrieval phases
The system SHALL expose `get_metrics_summary` and the extended
`get_log_lines`, including their alert time and window arguments, as typed
functions on `read_mcp_client`, callable without constructing raw MCP tool
arguments.

#### Scenario: Both phases are callable through the typed client
- **GIVEN** the `argus-read-mcp` server is running with an active scenario
- **WHEN** `read_mcp_client.get_metrics_summary()` is called, and then
  `read_mcp_client.get_log_lines(bucket_ids=...)` with bucket ids taken from
  its result
- **THEN** both calls succeed and the log lines returned fall within the named
  buckets
