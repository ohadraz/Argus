## MODIFIED Requirements

### Requirement: argus-read-mcp exposes get_metrics_summary
The system SHALL provide a
`get_metrics_summary(alert_time, window_start, window_end)` tool on
`argus-read-mcp` returning per-minute pre-aggregated buckets - each
carrying its bucket id, error rate, p50 and p95 latency, and request volume -
for the Target Service, read through the configured metrics source and asked
of it for the resolved window rather than fetched whole and filtered.

#### Scenario: A call with no window returns the configured span up to now
- **GIVEN** a scenario is active on the Target Service
- **WHEN** `get_metrics_summary` is called with no window
- **THEN** it returns the buckets of the last `metrics_window_minutes` up to
  now

#### Scenario: Buckets outside the window are excluded
- **GIVEN** a scenario is active whose buckets span several minutes
- **WHEN** `get_metrics_summary` is called with a window covering only some of
  those minutes
- **THEN** only the buckets whose minute falls inside the window are returned

#### Scenario: No active scenario yields no buckets
- **GIVEN** the Target Service has no active scenario
- **WHEN** `get_metrics_summary` is called
- **THEN** it returns an empty list

#### Scenario: An unreadable metrics source is not an empty summary
- **GIVEN** the metrics source cannot be read
- **WHEN** `get_metrics_summary` is called
- **THEN** the call fails, rather than returning an empty list
