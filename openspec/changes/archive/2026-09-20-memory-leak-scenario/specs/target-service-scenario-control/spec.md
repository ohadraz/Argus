## ADDED Requirements

### Requirement: A scenario's live condition may be a restart rather than a flag
The system SHALL allow a generated scenario to name a restart as the condition
its telemetry reacts to, in place of a feature flag. A flag is the wrong
condition for a fault that accumulates: the flip would fall hours outside every
window a reader retrieves, so it appears in no change history the reader sees,
and no flag causes a leak in any case.

The restart SHALL be exposed under the scenario-control prefix, SHALL reclaim
what the scenario has accumulated, and SHALL take effect for whoever calls it -
the demo console or Argus through the write tier - so that the telemetry cannot
distinguish who restarted the service.

#### Scenario: Restarting resets what the scenario accumulated
- **GIVEN** a staged scenario whose resource usage has climbed
- **WHEN** the restart control is called
- **THEN** the next buckets report usage back at its baseline and a changed
  process start time

#### Scenario: The accumulation begins again after a restart
- **GIVEN** a staged scenario that has just been restarted
- **WHEN** several minutes pass and `GET /metrics` is requested
- **THEN** usage is climbing again from the baseline, because the fault is
  still in the deployed code

#### Scenario: A restart by anyone has the same effect
- **GIVEN** a staged scenario whose usage has climbed
- **WHEN** the restart is performed through the demo console in one case and by
  Argus in another
- **THEN** the telemetry that follows is the same in both

## MODIFIED Requirements

### Requirement: Each scenario serves per-minute metric buckets
The system SHALL provide `GET /metrics`, returning the active scenario's
per-minute buckets for the period it covers - each carrying its minute, error
rate, p50 and p95 latency, request volume, memory used, memory limit and
process start time - with no filtering and no query parameters, mirroring
`GET /logs`. For a generated scenario the buckets are derived from the state of
its condition during each minute.

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
- **GIVEN** the `feature-flag-toggle` scenario is active in one case,
  `bad-deployment` in another and the memory-leak scenario in a third
- **WHEN** `GET /metrics` is requested for each
- **THEN** `feature-flag-toggle` shows an error-rate spike while the flag is
  on, `bad-deployment` shows a p95 latency spike after the deploy, and the
  memory-leak scenario shows memory climbing minute over minute
