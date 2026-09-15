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

## MODIFIED Requirements

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
