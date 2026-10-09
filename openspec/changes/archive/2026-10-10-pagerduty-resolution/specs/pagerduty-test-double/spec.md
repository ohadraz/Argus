## ADDED Requirements

### Requirement: The double answers PagerDuty's REST reads Argus makes

The system SHALL provide a stand-in for the PagerDuty REST reads Argus makes (an
incident, incidents by key, an incident's alerts, its notes, a user), shaped as
PagerDuty shapes them and reached through the vendor's own SDK. It SHALL serve
TLS, because the SDK refuses a plain-HTTP base URL.

#### Scenario: The SDK reads a staged incident

- **GIVEN** an incident staged in the double
- **WHEN** Argus's adapter reads it through the PagerDuty SDK
- **THEN** it receives the staged incident in PagerDuty's shape

#### Scenario: An incident found by its alert key

- **GIVEN** an incident staged with alert key `k`
- **WHEN** incidents are listed by incident key `k`
- **THEN** that incident is returned

### Requirement: Tests stage the double; the double knows no scenario

The system SHALL let a test stage an incident whole (its alert keys,
acknowledgements, users and notes) through `/double-control/*`, and SHALL clear
everything on reset. The double SHALL NOT derive anything from a scenario.

#### Scenario: Reset clears what was staged

- **GIVEN** an incident staged in the double
- **WHEN** the double is reset
- **THEN** reading that incident answers not found
