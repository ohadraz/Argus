# incident-lifecycle

## Purpose

TBD - covers the end-to-end lifecycle of an incident: alert ingestion via webhook,
Orchestrator invocation, the FSM's status transitions, timeline auditing, and state
persistence across the sub-agent graph (Investigator, Mitigation, Code-Fix,
Communicator, Postmortem) and the tier-gate node.
## Requirements
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
The system SHALL transition an incident through `investigating` → `mitigating` → `resolved` (spec §10) with no manual intervention, using stub sub-agent logic for Mitigation, Code-Fix, Communicator, and Postmortem. The Investigator performs real cause detection via the bounded ReAct loop (spec §9) - onset-anchored retrieval and an LLM verdict - for at least the `feature-flag-toggle` scenario. When no cause is determined, it reports a confidence below the mitigate threshold and the incident routes to `escalated` rather than continuing the happy path.

#### Scenario: No scenario seeded escalates rather than resolving
- **GIVEN** a new `Incident` in `investigating` status, and no scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines no cause at a confidence below the mitigate threshold, and the incident's final status is `escalated`

#### Scenario: Happy path resolves an incident with a real diagnosed cause
- **GIVEN** a new `Incident` in `investigating` status, and the `feature-flag-toggle` scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines `cause_type = "feature-flag-toggle"` at a confidence >= 0.75, the Mitigation stub reports the hypothesis `confirmed`, and the incident's final status is `resolved`

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
