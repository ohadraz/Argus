## MODIFIED Requirements

### Requirement: Each scenario serves per-minute metric buckets
The system SHALL provide `GET /scenario/metrics`, returning the active
scenario's per-minute buckets for the period it covers - each carrying its
minute, error rate, p50 and p95 latency, request volume, memory used, memory
limit and process start time - with no filtering and no query parameters,
mirroring `GET /logs`. For a generated scenario the buckets are derived from
the state of its condition during each minute. These rows are the shop's own
view, read by its console and by tests; Argus reads the same minutes through
the Prometheus stand-in, and `GET /metrics` is Prometheus's.

#### Scenario: Buckets are returned for the active scenario
- **GIVEN** a scenario is active
- **WHEN** `GET /scenario/metrics` is requested
- **THEN** it returns that scenario's per-minute buckets for the period it
  covers, unfiltered, in chronological order

#### Scenario: No active scenario yields no buckets
- **GIVEN** no scenario is active
- **WHEN** `GET /scenario/metrics` is requested
- **THEN** it returns an empty list

#### Scenario: Buckets share the log entries' anchor
- **GIVEN** a scenario is seeded
- **WHEN** both `GET /logs` and `GET /scenario/metrics` are requested
- **THEN** the minutes covered by the returned buckets correspond to the
  minutes of the returned log entries

#### Scenario: Each scenario's buckets reflect its own failure mode
- **GIVEN** the `feature-flag-toggle` scenario is active in one case,
  `bad-deployment` in another and the memory-leak scenario in a third
- **WHEN** `GET /scenario/metrics` is requested for each
- **THEN** `feature-flag-toggle` shows an error-rate spike while the flag is
  on, `bad-deployment` shows a p95 latency spike after the deploy, and the
  memory-leak scenario shows memory climbing minute over minute
