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

`mitigating` SHALL be re-enterable, and a refuted action SHALL self-loop on it.
The incident stays in `mitigating` for the next candidate rather than passing
through any other status on the way, and it leaves `mitigating` only on a
confirmed action, on an outcome that could not be taken at all, or when the walk
has run out of candidates and wider looks - in which last case it leaves for
`fixing`.

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

#### Scenario: An action that does not resolve the symptom is followed by the next candidate
- **GIVEN** an incident whose mitigation was taken and whose metrics still depart
  from baseline afterwards, and an untried candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the recorded outcome for that candidate is `refuted` and the incident
  remains in `mitigating` for the next candidate rather than leaving for `fixing`

#### Scenario: A walk with nothing left routes onward from mitigating
- **GIVEN** an incident whose candidates are all refuted and whose widening
  schedule has reached its maximum
- **WHEN** the graph runs to completion
- **THEN** the incident leaves `mitigating` for `fixing`, a human is paged, and
  the final status is not `resolved`

#### Scenario: A refuted incident leaves the environment as it was found
- **GIVEN** an incident whose mitigation was refuted
- **WHEN** the graph has run to completion
- **THEN** the state the action changed has been restored, and the incident's
  timeline records both the action and its undo

### Requirement: A status is written only when the incident enters it

The system SHALL write an `Incident.status` transition only for a status the
incident actually occupies. A status that is set and immediately overwritten by
the next node SHALL NOT be written at all, because the timeline and the event
stream are read as the account of where the incident has been, and a status it
passed through in name only is a claim about the incident that is not true.

#### Scenario: A refuted action does not pass through a status it never occupies

- **GIVEN** an incident whose mitigation was refuted and which has an untried
  candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the incident's timeline records no transition to `fixing`, and no
  `StatusChanged` event carrying `fixing` is published

### Requirement: `fixing` is the status of an incident a permanent fix is being sought for

The system SHALL use `fixing` for, and only for, an incident that has reached
Code-Fix - the point at which no reversible mitigation is left to try and the
remaining move is a code change. `fixing` SHALL NOT be terminal, because
Code-Fix is still working when it is set. `escalated` SHALL be reached only
once Argus has no move left at all, so that a human reading a status can tell
"Argus is still working on this" from "this is now yours".

#### Scenario: Reaching Code-Fix is recorded as fixing

- **GIVEN** an incident whose candidates are all refuted and whose widening
  schedule has reached its maximum
- **WHEN** the graph hands the incident to Code-Fix
- **THEN** the incident's status is `fixing`, and `fixing` reports itself as
  non-terminal

#### Scenario: A mid-walk refutation is not recorded as fixing

- **GIVEN** an incident whose mitigation was refuted and which has an untried
  candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the incident's status is `mitigating`, not `fixing`

### Requirement: Every FSM transition is recorded as a TimelineEvent row
The system SHALL write a `TimelineEvent` row (spec §11.1) for every
`Incident.status` transition, in the same transaction as the status update, per
the Orchestrator's single-writer rule.

A `TimelineEvent` row SHALL also be writable without a status transition, for
work that is worth recording and did not move the incident - an action refused
at the tier gate being the case that matters. Such a row SHALL carry the status
the incident is already in. Writing a transition and writing a note are
therefore two operations, and only the first updates `Incident.status`.

#### Scenario: Transition produces a timeline entry
- **GIVEN** an incident currently in `investigating` status
- **WHEN** the graph transitions it to `mitigating`
- **THEN** a new `TimelineEvent` row exists for that incident recording the transition

#### Scenario: Work that settles nothing produces a timeline entry without a transition
- **GIVEN** an incident in `mitigating` status whose proposed action is refused
  at the tier gate
- **WHEN** the gate records the refusal
- **THEN** a new `TimelineEvent` row exists naming the refusal and its reason,
  carrying `mitigating`, and `Incident.status` is unchanged

### Requirement: IncidentState persists via LangGraph checkpointing
The system SHALL persist `IncidentState` (spec §11.1) to Postgres via LangGraph's built-in
checkpointing (spec §7.1).

#### Scenario: State survives a process restart mid-incident
- **GIVEN** an incident that has reached `mitigating` status
- **WHEN** the Orchestrator process restarts
- **THEN** the graph resumes the incident from its last checkpointed state, without
  re-running already-completed steps

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

### Requirement: An action row records what it did and how to undo it
The system SHALL persist, for every action taken, its type, its outcome, and the
undo descriptor returned with it, so that the record of an incident says what was
changed and what would restore it.

#### Scenario: A flag revert is recorded with its undo descriptor
- **GIVEN** an incident in which a flag was reverted
- **WHEN** the incident's action rows are read
- **THEN** the row for that action carries its outcome and an undo descriptor
  naming the flag and the state it had been in

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

### Requirement: A human is kept informed during a walk and paged once at its end
The system SHALL post an update for a human after each refuted or rejected attempt while candidates or wider looks remain, saying what was tried, what it did, and what is next. It SHALL raise a page exactly once, when the walk ends without a confirmed fix. A page SHALL NOT be raised per refuted attempt.

#### Scenario: Refutations mid-walk inform rather than page
- **GIVEN** an incident with three candidates
- **WHEN** the first two are refuted
- **THEN** two updates are posted and no page is raised

#### Scenario: The end of a walk pages once
- **GIVEN** an incident whose walk has exhausted its candidates and its schedule
- **WHEN** the walk ends
- **THEN** exactly one page is raised

### Requirement: An incident records when it ended
The system SHALL record the time an incident ended, at the transition that ends
it, whether it ended resolved or escalated. How long an incident lasted is a
figure Argus reports, so it SHALL be recorded rather than inferred from
whichever row happened to be written last - an inference that would change
silently the moment anything is logged late.

#### Scenario: A terminal transition stamps the end
- **WHEN** an incident transitions into a terminal status
- **THEN** the incident records the time of that transition as its end

#### Scenario: A running incident has no end
- **WHEN** an incident has not reached a terminal status
- **THEN** it records no end time
