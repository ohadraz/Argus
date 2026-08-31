## MODIFIED Requirements

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
