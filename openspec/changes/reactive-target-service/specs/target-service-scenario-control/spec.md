## MODIFIED Requirements

### Requirement: A registry of pre-seeded scenarios exists, each simulating a different incident cause
The system SHALL maintain at least two scenarios, each identified by a scenario
id and each staging what a real incident of that cause would have produced. A
scenario SHALL declare how its content is produced: either a fixed list of log
entries authored in advance, or generation from a live condition the scenario
seeds and anything may subsequently change. Where a scenario is generated, its
content for a given minute SHALL be derived from the state of that condition
during that minute, and SHALL NOT be authored in advance.

#### Scenario: The feature-flag-toggle scenario reads as a flag-caused error spike
- **GIVEN** the `feature-flag-toggle` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe an elevated error rate arising from
  the feature flag being on

#### Scenario: The bad-deployment scenario reads as a deployment-caused latency spike
- **GIVEN** the `bad-deployment` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe a deployment and a resulting
  latency spike

#### Scenario: A generated scenario's content follows its condition
- **GIVEN** a scenario whose content is generated from a live condition
- **WHEN** that condition changes and `GET /logs` is requested again
- **THEN** the content for minutes after the change reflects the new state of
  the condition

### Requirement: `/logs` returns the active scenario's full pre-seeded log content
The system SHALL expose `GET /logs` on the Target Service, returning the
currently active scenario's complete log content for the period it covers,
unfiltered, in chronological order - or an empty list if no scenario is active.
For an authored scenario that content is its pre-seeded list; for a generated
scenario it is the lines its condition produced over that period.

#### Scenario: No scenario active returns no logs
- **GIVEN** no scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns an empty list

#### Scenario: An active scenario's logs are returned in full
- **GIVEN** a scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns that scenario's complete log content for the period it
  covers, unfiltered, in chronological order

#### Scenario: Switching the active scenario switches the returned logs
- **GIVEN** the `feature-flag-toggle` scenario is active and `GET /logs` has been requested
- **WHEN** `POST /scenario/seed` is called with the `bad-deployment` scenario id
- **THEN** a subsequent `GET /logs` request returns the `bad-deployment` scenario's log entries, not the previous scenario's

### Requirement: Scenario log entries carry timestamps anchored to seed time
The system SHALL timestamp every scenario log entry, deriving each timestamp
from the instant the scenario was seeded or from the clock as the scenario
progresses, rather than from an absolute literal authored into the fixture, so
that a freshly seeded scenario always reads as recent.

#### Scenario: Entries are timestamped relative to when the scenario was seeded
- **GIVEN** a scenario is seeded via `POST /scenario/seed`
- **WHEN** `GET /logs` is requested
- **THEN** each returned entry carries a timestamp derived from the seed
  instant or from the time that has elapsed since it

#### Scenario: Already-elapsed minutes read the same on re-reading
- **GIVEN** a scenario was seeded and `GET /logs` has already been requested
- **WHEN** `GET /logs` is requested again later, without re-seeding
- **THEN** the entries for minutes that had already completed at the time of the
  first request are unchanged, while minutes that have elapsed since may carry
  new entries

### Requirement: Each scenario serves per-minute metric buckets
The system SHALL provide `GET /metrics`, returning the active scenario's
per-minute buckets for the period it covers - each carrying its minute, error
rate, p50 and p95 latency, and request volume - with no filtering and no query
parameters, mirroring `GET /logs`. For a generated scenario the buckets are
derived from the state of its condition during each minute.

#### Scenario: Buckets are returned for the active scenario
- **GIVEN** a scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns that scenario's per-minute buckets for the period it
  covers, unfiltered, in chronological order

#### Scenario: No active scenario yields no buckets
- **GIVEN** no scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns an empty list

#### Scenario: Buckets share the log entries' anchor
- **GIVEN** a scenario is seeded
- **WHEN** both `GET /logs` and `GET /metrics` are requested
- **THEN** the minutes covered by the returned buckets correspond to the
  minutes of the returned log entries

#### Scenario: Each scenario's buckets reflect its own failure mode
- **GIVEN** the `feature-flag-toggle` scenario is active in one case and
  `bad-deployment` in another
- **WHEN** `GET /metrics` is requested for each
- **THEN** `feature-flag-toggle` shows an error-rate spike while the flag is on,
  and `bad-deployment` shows a p95 latency spike after the deploy

## ADDED Requirements

### Requirement: Seeding a generated scenario establishes its live condition
The system SHALL, when a generated scenario is seeded, put its condition into
the state that scenario stages, and SHALL record when that state began. The
recorded beginning MAY be placed a configured interval in the past, so that an
incident with enough history to be diagnosed exists immediately upon seeding.

#### Scenario: Seeding turns the flag on
- **GIVEN** the flag is off
- **WHEN** `POST /scenario/seed` is called with `feature-flag-toggle`
- **THEN** the flag is on afterwards, as the provider reports it

#### Scenario: An incident exists immediately
- **GIVEN** `POST /scenario/seed` has just been called with `feature-flag-toggle`
- **WHEN** `GET /metrics` is requested
- **THEN** several already-completed minutes carry an elevated error rate,
  without waiting for time to pass

#### Scenario: Seeding is not needed a second time
- **GIVEN** `feature-flag-toggle` was seeded and time has passed
- **WHEN** `GET /metrics` is requested
- **THEN** the minutes that elapsed since seeding also carry an elevated error
  rate, for as long as the flag remains on

### Requirement: Resetting clears a generated scenario's live condition
The system SHALL, when scenario control is reset, return the condition of a
generated scenario to its non-incident state, so that no incident is left
running against the next reader.

#### Scenario: Reset turns the flag off
- **GIVEN** `feature-flag-toggle` is active and the flag is on
- **WHEN** `POST /scenario/reset` is called
- **THEN** the flag is off afterwards, as the provider reports it

#### Scenario: Reset stops the anomaly
- **GIVEN** `feature-flag-toggle` is active
- **WHEN** `POST /scenario/reset` is called and a further minute elapses
- **THEN** `GET /metrics` reports that minute at the healthy baseline

### Requirement: The condition may be changed by anyone
The system SHALL derive a generated scenario's content from the current state of
its condition regardless of who changed that state or how, so that a party other
than scenario control - a human in the provider's console, or an automated agent
- can end the incident.

#### Scenario: An externally reverted flag ends the incident
- **GIVEN** `feature-flag-toggle` is active and the flag is on
- **WHEN** the flag is turned off by a party other than scenario control
- **THEN** subsequent reads of `GET /metrics` show recovery, and
  `GET /scenario/status` still reports the scenario as active
