## ADDED Requirements

### Requirement: An incident's status is a pure function of its state

The system SHALL derive an incident's status from its state through a single
pure function. That function SHALL be total over the states the graph can
produce, SHALL perform no I/O, and SHALL NOT consult a language model - the
evidence a status rests on has already been measured, and re-deriving it by
inference would make the auditable part of an incident depend on a sampled call.

#### Scenario: The same state always yields the same status

- **GIVEN** any incident state
- **WHEN** the status is derived from it twice
- **THEN** both derivations return the same status, with no call to a model, a
  database, or a network

#### Scenario: A confirmed action yields resolved

- **GIVEN** a state whose action outcome is `confirmed`
- **WHEN** the status is derived
- **THEN** it is `resolved`

#### Scenario: A refuted action with a candidate left yields mitigating

- **GIVEN** a state whose action outcome is `refuted` and which has an untried
  candidate above the mitigate threshold
- **WHEN** the status is derived
- **THEN** it is `mitigating`

#### Scenario: A walk out of candidates and rounds yields fixing

- **GIVEN** a state with no untried candidate and no investigation round left
- **WHEN** the status is derived
- **THEN** it is `fixing`

#### Scenario: An investigation that found nothing actionable yields escalated

- **GIVEN** a state whose investigation reported no candidate worth trying
- **WHEN** the status is derived
- **THEN** it is `escalated`, whether or not investigation rounds remain -
  the loop has already widened as far as it can within the round

### Requirement: Nodes do not decide status

No graph node SHALL return a status or write one. A node SHALL return only the
work it did - a verdict, a hypothesis, attempts, a proposed action - and a line
of narration describing it. The status a node's work implies SHALL be derived
from the resulting state after the node returns.

#### Scenario: A node returns work, not a status

- **GIVEN** any node in the graph
- **WHEN** it is invoked and returns its updates
- **THEN** those updates contain no status, and the node made no call that
  persists one

#### Scenario: The derived status is what the incident carries

- **GIVEN** a node whose work implies a new status
- **WHEN** the node returns
- **THEN** the incident's status is the one derived from the resulting state

### Requirement: A status change is persisted and published exactly once

The system SHALL persist and publish a status change once, in one place, when
and only when the derived status differs from the status the node was entered
with. A node SHALL NOT be responsible for noticing that the status changed.

#### Scenario: An unchanged status is not written

- **GIVEN** a node whose work leaves the derived status equal to the one it was
  entered with
- **WHEN** the node returns
- **THEN** no status transition is persisted and no `StatusChanged` event is
  published

#### Scenario: A changed status is written once

- **GIVEN** a node whose work changes the derived status
- **WHEN** the node returns
- **THEN** exactly one transition is persisted and exactly one `StatusChanged`
  event is published

### Requirement: Narration is recorded whether or not the status moved

The system SHALL record a node's narration on the incident's timeline
independently of whether the status changed, so that work which settles nothing
- an action refused at the tier gate, a candidate skipped - is still visible to
a human reading the incident.

#### Scenario: A rejection at the gate is on the timeline

- **GIVEN** a proposed action the tier gate refuses
- **WHEN** the gate returns
- **THEN** the incident's timeline carries a row naming the rejection and its
  reason, and no status transition is persisted, because the incident was
  already `mitigating`

#### Scenario: The actor on a row is the agent the node belongs to

- **GIVEN** a node registered in the graph as belonging to an agent
- **WHEN** it records narration or a transition
- **THEN** the row carries that agent as its actor
