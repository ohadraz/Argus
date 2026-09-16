# incident-status-derivation Specification

## Purpose
Where an incident stands, and who decides it. The state machine of spec §10 stated once as a pure function of the incident's state, so that no node decides a status and no status is written for a state the incident never occupied.
## Requirements
### Requirement: An incident's status is a pure function of its state

The system SHALL derive an incident's status from its state through a single
pure function. That function SHALL be total over the states the graph can
produce, SHALL perform no I/O, and SHALL NOT consult a language model - the
evidence a status rests on has already been measured, and re-deriving it by
inference would make the auditable part of an incident depend on a sampled call.

#### Scenario: The same state always yields the same status

- **WHEN** the status is derived from the same incident state twice
- **THEN** both derivations return the same status, with no call to a model, a
  database, or a network

#### Scenario: A confirmed action yields mitigated

- **GIVEN** a state whose action outcome is `confirmed`
- **WHEN** the status is derived
- **THEN** it is `mitigated` - the symptom stopped, which is as far as a
  reversible action can take an incident

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

### Requirement: A withdrawal overrides the status the walk would derive

Where an incident has been withdrawn, the system SHALL keep `withdrawn` as its
status regardless of what the walk's state would otherwise derive, and SHALL NOT
write a transition out of it. Withdrawal is a fact about the incident recorded
from outside; the derivation is a pure function of the walk's state and cannot
see it, so a node returning after a withdrawal would otherwise write the status
its own work implied and quietly revive an incident a human had ended.

#### Scenario: A node returning after a withdrawal does not move the status

- **GIVEN** an incident withdrawn while a node was running
- **WHEN** that node returns work whose derived status is `mitigating`
- **THEN** the incident's status remains `withdrawn`, and no transition to
  `mitigating` is persisted or published

#### Scenario: The derivation itself is unchanged

- **GIVEN** any walk state
- **WHEN** its status is derived
- **THEN** the derivation performs no I/O and never returns `withdrawn`, which
  is set only by the withdrawal itself

### Requirement: A mitigated incident is its own ending
The system SHALL record an incident whose symptom stopped by a reversible action
as `mitigated` rather than `resolved`. `mitigated` SHALL be terminal: it is as
far as Argus can take the incident, and what would move it on is a person's to
do.

#### Scenario: A confirmed action mitigates
- **GIVEN** an action whose verdict is confirmed against re-queried metrics
- **WHEN** the status is derived
- **THEN** the incident is `mitigated`

#### Scenario: Mitigated has nowhere left to go
- **WHEN** anything asks whether a mitigated incident is still going
- **THEN** it is told the incident has ended, so a page polling it stops

### Requirement: The status answers whether the symptom stopped
The system SHALL derive the status from whether the symptom stopped, asking
that question before any other. Whether a code fix was found SHALL decide what
the incident *carries* rather than what state it is in. The system SHALL NOT
derive `resolved`: a mitigation stops a symptom and a draft pull request
proposes a change nobody has made, and neither ends the cause.

#### Scenario: A mitigated incident that also got a fix stays mitigated
- **GIVEN** a confirmed action and a pull request proposed afterwards
- **WHEN** the status is derived
- **THEN** the incident is `mitigated`, not escalated - the order of the
  questions is what guarantees it

#### Scenario: A fix found without a mitigation still escalates
- **GIVEN** a walk that reached Code-Fix having stopped nothing
- **WHEN** a fix is proposed
- **THEN** the incident is `escalated`: the symptom is still happening, and a
  proposal does not stop it

#### Scenario: Resolved is never derived
- **WHEN** any state is put to the derivation
- **THEN** `resolved` is not the answer, because merging is outside Argus's
  autonomy and nothing here can observe one

### Requirement: A mitigation that worked goes on to look for a fix
The system SHALL route an incident whose mitigation was confirmed to the
Code-Fix step before the postmortem, so the fault the mitigation held off is
looked at. Code-Fix SHALL therefore be reachable by two roads: Argus having run
out of reversible moves, and Argus having made one that worked. Every incident
reaching Code-Fix SHALL go on to the postmortem.

#### Scenario: A successful mitigation is followed by a fix attempt
- **GIVEN** a confirmed mitigation
- **WHEN** the walk continues
- **THEN** it reaches Code-Fix, and then the postmortem

#### Scenario: An incident nothing could be done for is still written up
- **GIVEN** an incident that reached Code-Fix having stopped nothing
- **WHEN** Code-Fix has had its turn
- **THEN** the incident goes to the postmortem, whatever the outcome was

