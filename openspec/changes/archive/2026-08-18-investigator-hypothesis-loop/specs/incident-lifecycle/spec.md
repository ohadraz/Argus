## MODIFIED Requirements

### Requirement: FSM completes the investigating → mitigating → resolved happy path
The system SHALL transition an incident through `investigating` → `mitigating` → `resolved` (spec §10) with no manual intervention, using stub sub-agent logic for Mitigation, Code-Fix, Communicator, and Postmortem. The Investigator performs real cause detection (deterministic log-based matching against the Target Service's `/logs`) for at least the `feature-flag-toggle` scenario, and falls back to the same fixed-confidence stub behavior as before when no known scenario is active.

#### Scenario: Stub happy path resolves an incident end-to-end with no scenario seeded
- **GIVEN** a new `Incident` in `investigating` status, and no scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator falls back to its pre-existing fixed-confidence behavior (no determined cause), the Mitigation stub reports the hypothesis `confirmed`, and the incident's final status is `resolved`

#### Scenario: Happy path resolves an incident with a real diagnosed cause
- **GIVEN** a new `Incident` in `investigating` status, and the `feature-flag-toggle` scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines `cause_type = "feature-flag-toggle"` at a confidence >= 0.75, the Mitigation stub reports the hypothesis `confirmed`, and the incident's final status is `resolved`
