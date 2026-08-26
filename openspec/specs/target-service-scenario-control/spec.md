# target-service-scenario-control Specification

## Purpose
TBD - created by archiving change target-service-scenario-and-logs. Update Purpose after archive.
## Requirements
### Requirement: A registry of pre-seeded scenarios exists, each simulating a different incident cause
The system SHALL maintain at least two pre-seeded scenarios, each identified by a scenario id and each a fixed list of log entries representing what a real incident of that cause would have produced. No scenario's log content SHALL be generated at request time - it is authored in advance.

#### Scenario: The feature-flag-toggle scenario reads as a flag-caused error spike
- **GIVEN** the `feature-flag-toggle` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe a feature flag being toggled on and an elevated error rate resulting from it

#### Scenario: The bad-deployment scenario reads as a deployment-caused latency spike
- **GIVEN** the `bad-deployment` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe a deployment and a resulting latency spike

### Requirement: Scenario control can activate a pre-seeded scenario by id, reset it, and report status
The system SHALL provide `POST /scenario/seed` (activates a named scenario), `POST /scenario/reset` (deactivates the current scenario), and `GET /scenario/status` (reports which scenario, if any, is currently active).

#### Scenario: Seeding a known scenario id activates it
- **GIVEN** no scenario is currently active
- **WHEN** `POST /scenario/seed` is called with a known scenario id
- **THEN** `GET /scenario/status` reports that scenario id as active

#### Scenario: Seeding an unknown scenario id fails
- **GIVEN** no scenario is currently active
- **WHEN** `POST /scenario/seed` is called with a scenario id that isn't in the registry
- **THEN** it responds with an error status and no scenario becomes active

#### Scenario: Resetting deactivates the current scenario
- **GIVEN** a scenario is currently active
- **WHEN** `POST /scenario/reset` is called
- **THEN** `GET /scenario/status` reports no scenario as active, and subsequent `GET /logs` requests return an empty list

### Requirement: `/logs` returns the active scenario's full pre-seeded log content
The system SHALL expose `GET /logs` on the Target Service, returning the currently active scenario's complete list of pre-seeded log entries, unfiltered, in the order they were authored - or an empty list if no scenario is active.

#### Scenario: No scenario active returns no logs
- **GIVEN** no scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns an empty list

#### Scenario: An active scenario's logs are returned in full
- **GIVEN** a scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns every log entry from that scenario's pre-seeded list, unfiltered, in authored order

#### Scenario: Switching the active scenario switches the returned logs
- **GIVEN** the `feature-flag-toggle` scenario is active and `GET /logs` has been requested
- **WHEN** `POST /scenario/seed` is called with the `bad-deployment` scenario id
- **THEN** a subsequent `GET /logs` request returns the `bad-deployment` scenario's log entries, not the previous scenario's

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


### Requirement: The Target Service serves deploy history in a real deployment tool's shape
The system SHALL provide an endpoint returning the active scenario's deploy
history in the response shape of a real continuous-delivery system, so that the
adapter reading it is the same code that would read the real one. The endpoint
SHALL echo back the application name it was asked about, as the real system
does, and SHALL answer from the active scenario regardless of which name that
is.

#### Scenario: A scenario with a deploy reports it
- **GIVEN** the `bad-deployment` scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns a revision history containing that scenario's deploy,
  carrying the minute it was deployed and the revision deployed

#### Scenario: A scenario without a deploy reports none
- **GIVEN** the `feature-flag-toggle` scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns an empty revision history, so that a deploy is not
  offered as a candidate cause for an incident no deploy caused

#### Scenario: No active scenario yields no history
- **GIVEN** no scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns an empty revision history

#### Scenario: The requested application name is echoed back
- **GIVEN** the deploy history endpoint is requested for some application name
- **WHEN** the response is returned
- **THEN** it identifies the application by the name that was requested

### Requirement: Deploy history shares the scenario's seed anchor
The system SHALL anchor deploy timestamps to the same seed instant as the
scenario's log entries and metric buckets, so that a deploy lands at the minute
of the incident it caused rather than at a fixed date.

#### Scenario: The deploy precedes the symptoms it caused
- **GIVEN** the `bad-deployment` scenario is seeded
- **WHEN** its deploy history and its metric buckets are compared
- **THEN** the deploy's time falls at or before the first bucket whose latency
  departs from the baseline
