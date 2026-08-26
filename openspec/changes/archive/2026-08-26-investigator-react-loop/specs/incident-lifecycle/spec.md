## MODIFIED Requirements

### Requirement: FSM completes the investigating → mitigating → resolved happy path
The system SHALL transition an incident through `investigating` → `mitigating` → `resolved` (spec §10) with no manual intervention, using stub sub-agent logic for Mitigation, Code-Fix, Communicator, and Postmortem. The Investigator performs real cause detection via the bounded ReAct loop (spec §9) - onset-anchored retrieval and an LLM verdict - for at least the `feature-flag-toggle` scenario. When no cause is determined, it reports a confidence below the mitigate threshold and the incident routes to `escalated` rather than continuing the happy path.

#### Scenario: No scenario seeded escalates rather than resolving
- **GIVEN** a new `Incident` in `investigating` status, and no scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines no cause at a confidence below the mitigate threshold, and the incident's final status is `escalated`

#### Scenario: Happy path resolves an incident with a real diagnosed cause
- **GIVEN** a new `Incident` in `investigating` status, and the `feature-flag-toggle` scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines `cause_type = "feature-flag-toggle"` at a confidence >= 0.75, the Mitigation stub reports the hypothesis `confirmed`, and the incident's final status is `resolved`

## ADDED Requirements

### Requirement: Escalation on insufficient evidence is distinguishable from a confident outcome
The system SHALL record, on an incident that escalated because investigation
exhausted its iterations or its window span, that the escalation was for
insufficient evidence - so a human picking it up can tell "Argus could not
determine the cause" from "Argus was confident and something else failed".

#### Scenario: An exhausted investigation is recorded as insufficient evidence
- **GIVEN** an incident whose investigation exhausted its iteration budget with no
  hypothesis reaching the mitigate threshold
- **WHEN** the incident transitions to `escalated`
- **THEN** the timeline records that the escalation was for insufficient evidence
