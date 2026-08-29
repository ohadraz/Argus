## MODIFIED Requirements

### Requirement: FSM completes the investigating → mitigating → resolved happy path
The system SHALL transition an incident through `investigating` → `mitigating` →
`resolved` (spec §10) with no manual intervention, using stub sub-agent logic for
Code-Fix, Communicator, and Postmortem. The Investigator performs real cause
detection via the bounded ReAct loop (spec §9) - onset-anchored retrieval and an
LLM verdict - for at least the `feature-flag-toggle` scenario. Mitigation
performs a real reversible action and returns a verdict measured from re-queried
metrics: `resolved` SHALL follow only from a `confirmed` verdict, so an incident
is never marked resolved while the condition that caused it is still in effect.
When no cause is determined, the Investigator reports a confidence below the
mitigate threshold and the incident routes to `escalated` rather than continuing
the happy path.

#### Scenario: No scenario seeded escalates rather than resolving
- **GIVEN** a new `Incident` in `investigating` status, and no scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines no cause at a confidence below the mitigate threshold, and the incident's final status is `escalated`

#### Scenario: Happy path resolves an incident with a real diagnosed cause
- **GIVEN** a new `Incident` in `investigating` status, and the `feature-flag-toggle` scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines `cause_type = "feature-flag-toggle"` at a
  confidence >= 0.75, Mitigation turns the flag off and confirms recovery from
  the metrics, and the incident's final status is `resolved`

#### Scenario: A resolved incident leaves the condition ended
- **GIVEN** an incident that reached `resolved`
- **WHEN** the flag provider is asked for the flag's state
- **THEN** the flag is off

#### Scenario: An action that does not resolve the symptom routes to fixing
- **GIVEN** an incident whose mitigation was taken and whose metrics still depart
  from baseline afterwards
- **WHEN** the graph runs to completion
- **THEN** the recorded outcome is `refuted` and the incident's status is
  `fixing`, not `resolved`

#### Scenario: A refuted incident leaves the environment as it was found
- **GIVEN** an incident whose mitigation was refuted
- **WHEN** the graph has run to completion
- **THEN** the state the action changed has been restored, and the incident's
  timeline records both the action and its undo

### Requirement: All sub-agent nodes and the tier-gate node exist in the graph
The system SHALL include a node for every sub-agent named in spec §7
(Investigator, Mitigation, Code-Fix, Communicator, Postmortem) and the tier-gate
node (spec §13) in the `StateGraph`. The tier-gate node SHALL stand between a
proposed action and the call that performs it, and SHALL reject any reversible
action whose undo descriptor is absent or empty, so that the guarantee does not
rest on the agent that performs the write also policing itself.

#### Scenario: Graph shape matches the full FSM
- **GIVEN** the assembled `StateGraph`
- **WHEN** its nodes and edges are inspected
- **THEN** a node exists for each of the five sub-agents and the tier-gate node, and edges
  exist for every transition in spec §10's state diagram, including `fixing` and
  `escalated`

#### Scenario: An action without an undo descriptor never reaches its call
- **GIVEN** a proposed reversible action carrying no undo descriptor
- **WHEN** the graph runs
- **THEN** no state-changing call is made and the incident escalates

## ADDED Requirements

### Requirement: An action row records what it did and how to undo it
The system SHALL persist, for every action taken, its type, its outcome, and the
undo descriptor returned with it, so that the record of an incident says what was
changed and what would restore it.

#### Scenario: A flag revert is recorded with its undo descriptor
- **GIVEN** an incident in which a flag was reverted
- **WHEN** the incident's action rows are read
- **THEN** the row for that action carries its outcome and an undo descriptor
  naming the flag and the state it had been in
