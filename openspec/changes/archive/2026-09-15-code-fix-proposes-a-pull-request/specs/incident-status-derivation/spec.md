## ADDED Requirements

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

## MODIFIED Requirements

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
