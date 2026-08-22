## ADDED Requirements

### Requirement: Scenario log entries carry timestamps anchored to seed time
The system SHALL timestamp every scenario log entry, deriving each timestamp
as a fixed offset from the instant the scenario was seeded rather than from an
absolute literal authored into the fixture, so that a freshly seeded scenario
always reads as recent.

#### Scenario: Entries are timestamped relative to when the scenario was seeded
- **GIVEN** a scenario is seeded via `POST /scenario/seed`
- **WHEN** `GET /logs` is requested
- **THEN** each returned entry carries a timestamp derived from the seed
  instant, in the authored order of the scenario's entries

#### Scenario: Re-reading a seeded scenario returns stable timestamps
- **GIVEN** a scenario was seeded and `GET /logs` has already been requested
- **WHEN** `GET /logs` is requested again later, without re-seeding
- **THEN** the returned timestamps are identical to those returned before

### Requirement: Each scenario serves per-minute metric buckets
The system SHALL provide `GET /metrics`, returning the active scenario's full
list of per-minute pre-aggregated buckets - each carrying its minute, error
rate, p50 and p95 latency, and request volume - with no filtering and no query
parameters, mirroring `GET /logs`.

#### Scenario: Buckets are returned for the active scenario
- **GIVEN** a scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns that scenario's full list of per-minute buckets,
  unfiltered, in chronological order

#### Scenario: No active scenario yields no buckets
- **GIVEN** no scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns an empty list

#### Scenario: Buckets share the log entries' seed anchor
- **GIVEN** a scenario is seeded
- **WHEN** both `GET /logs` and `GET /metrics` are requested
- **THEN** the minutes covered by the returned buckets correspond to the
  minutes of the returned log entries

#### Scenario: Each scenario's buckets reflect its own failure mode
- **GIVEN** the `feature-flag-toggle` scenario is active in one case and
  `bad-deployment` in another
- **WHEN** `GET /metrics` is requested for each
- **THEN** `feature-flag-toggle` shows an error-rate spike after the toggle,
  and `bad-deployment` shows a p95 latency spike after the deploy
