## ADDED Requirements

### Requirement: Investigator determines cause_type from the Target Service's current logs
The system SHALL call the Target Service's `GET /logs` endpoint during investigation and use deterministic keyword matching against the returned log entries to determine a `cause_type` for at least the `feature-flag-toggle` scenario.

#### Scenario: Feature-flag-toggle logs are recognized
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `cause_type = "feature-flag-toggle"` at a confidence high enough to route to `mitigating`

#### Scenario: No recognizable logs fall back to an undetermined cause
- **GIVEN** the Target Service has no active scenario (`GET /logs` returns an empty list)
- **WHEN** the Investigator investigates the incident
- **THEN** it records a hypothesis with `cause_type` left undetermined (`NULL`), at the same confidence the Investigator used before this change

### Requirement: cause_type is persisted on the hypothesis row
The system SHALL write the determined `cause_type` (or leave it `NULL` if undetermined) to the `hypothesis` table's `cause_type` column, in addition to `description` and `confidence`.

#### Scenario: A determined cause is persisted
- **GIVEN** the Investigator determines `cause_type = "feature-flag-toggle"` for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the `hypothesis` row for that incident has `cause_type = 'feature-flag-toggle'`
