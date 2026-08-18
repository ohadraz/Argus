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

