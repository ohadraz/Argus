# node-testability Specification

## Purpose
TBD - created by archiving change test-coverage-hardening. Update Purpose after archive.
## Requirements
### Requirement: The repository layer has integration test coverage
The system SHALL have integration test coverage for `orchestrator/repository`'s core read/write paths - creating an incident, transitioning its status, and the atomic pairing with the resulting timeline events - verified against a real Postgres connection.

#### Scenario: Creating an incident writes the expected rows
- **GIVEN** an alert
- **WHEN** `incidents.create` is called with it
- **THEN** the resulting incident is in `investigating` status and exactly one `investigating` timeline event exists for it

#### Scenario: Transitioning an incident updates status and appends a timeline event
- **GIVEN** an incident that was created
- **WHEN** `incidents.transition` moves it to `mitigating`
- **THEN** the incident's status is `mitigating`, and the timeline shows `investigating` followed by `mitigating`

### Requirement: investigator_node's investigate dependency is injectable
The system SHALL allow `investigator_node` to accept an injectable `investigate` callable, defaulting to `agent_investigator.investigate`, so its own logic can be tested independently of a live Target Service.

#### Scenario: Default behavior is unchanged
- **GIVEN** no explicit `investigate` argument is passed to `investigator_node`
- **WHEN** it runs
- **THEN** it uses `agent_investigator.investigate` exactly as before

#### Scenario: A stub investigate can be injected for testing
- **GIVEN** a stub `investigate` callable returning a known hypothesis, confidence, and cause_type
- **WHEN** `investigator_node` runs with that stub injected
- **THEN** it uses the stub's return values to determine routing and to persist the hypothesis, without calling the real Target Service

### Requirement: investigator_node's routing and persistence logic is directly tested
The system SHALL have direct (non-e2e) test coverage confirming `investigator_node` correctly routes to `mitigating` or `escalated` based on confidence, and correctly persists the hypothesis and status transition.

#### Scenario: High confidence routes to mitigating and persists correctly
- **GIVEN** an injected `investigate` stub returning confidence >= the mitigate threshold
- **WHEN** `investigator_node` runs
- **THEN** it routes to `mitigating`, and the hypothesis and transition are persisted via the repository layer with the stub's values

#### Scenario: Low confidence routes to escalated and persists correctly
- **GIVEN** an injected `investigate` stub returning confidence below the mitigate threshold
- **WHEN** `investigator_node` runs
- **THEN** it routes to `escalated`, and the hypothesis and transition are persisted via the repository layer with the stub's values

