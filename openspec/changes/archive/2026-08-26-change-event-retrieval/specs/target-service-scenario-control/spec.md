## ADDED Requirements

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
