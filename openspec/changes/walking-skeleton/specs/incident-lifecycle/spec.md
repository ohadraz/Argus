## ADDED Requirements

### Requirement: `argus_web` receives the alert webhook and invokes the Orchestrator in-process
The system SHALL expose an alert webhook endpoint on `argus_web` (spec §7.9) that validates
the incoming payload and invokes the Orchestrator's entrypoint in-process (spec §7.1),
which creates a new `Incident` row and invokes the graph.

#### Scenario: Webhook call starts a new incident
- **GIVEN** `argus_web`'s alert webhook endpoint is running
- **WHEN** a webhook call is received with a valid alert payload
- **THEN** `argus_web` validates the payload and invokes the Orchestrator's entrypoint
  in-process, which creates a new `Incident` row with `status = investigating` and invokes
  the graph with that incident's state

### Requirement: FSM completes the investigating → mitigating → resolved happy path
The system SHALL transition an incident through `investigating` → `mitigating` →
`resolved` (spec §10) using stub sub-agent logic, with no manual intervention.

#### Scenario: Stub happy path resolves an incident end-to-end
- **GIVEN** a new `Incident` in `investigating` status
- **WHEN** the graph runs to completion
- **THEN** the Investigator stub returns a fixed hypothesis at confidence >= 0.75, the
  Mitigation stub reports the hypothesis `confirmed`, and the incident's final status is
  `resolved`

### Requirement: Every FSM transition is recorded as a TimelineEvent row
The system SHALL write a `TimelineEvent` row (spec §11.1) for every `Incident.status`
transition.

#### Scenario: Transition produces a timeline entry
- **GIVEN** an incident currently in `investigating` status
- **WHEN** the graph transitions it to `mitigating`
- **THEN** a new `TimelineEvent` row exists for that incident recording the transition

### Requirement: IncidentState persists via LangGraph checkpointing
The system SHALL persist `IncidentState` (spec §11.1) to Postgres via LangGraph's built-in
checkpointing (spec §7.1).

#### Scenario: State survives a process restart mid-incident
- **GIVEN** an incident that has reached `mitigating` status
- **WHEN** the Orchestrator process restarts
- **THEN** the graph resumes the incident from its last checkpointed state, without
  re-running already-completed steps

### Requirement: All sub-agent nodes and the tier-gate node exist in the graph
The system SHALL include a node for every sub-agent named in spec §7 (Investigator,
Mitigation, Code-Fix, Communicator, Postmortem) and the tier-gate node (spec §13) in the
`StateGraph`, regardless of whether this change's happy path drives all of them.

#### Scenario: Graph shape matches the full FSM
- **GIVEN** the assembled `StateGraph`
- **WHEN** its nodes and edges are inspected
- **THEN** a node exists for each of the five sub-agents and the tier-gate node, and edges
  exist for every transition in spec §10's state diagram, including `fixing` and
  `escalated`
