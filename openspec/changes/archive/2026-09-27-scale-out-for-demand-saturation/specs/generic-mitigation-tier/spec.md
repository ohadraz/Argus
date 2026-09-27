## ADDED Requirements

### Requirement: A mitigation with a magnitude is bounded by a ceiling as well as by a cap
The system SHALL bound how far one application of a mitigation may go, for any
mitigation whose effect is a quantity rather than a state. The bound SHALL be
held by the tier that performs the action, because it is a fact about the estate
rather than about the incident, and SHALL be refused rather than exceeded.

It is a second bound and not a restatement of the cap. The cap bounds how many
times a repeatable mitigation may be applied to one subject within one incident;
this bounds how large any single application may be. Either alone leaves the
other's failure mode available - a cap of two with no ceiling permits an
unbounded second attempt, and a ceiling with no cap permits attempts without end
below it.

Every mitigation that restores a state needs only the cap, because the state it
restores is the bound: a flag has two positions and a revision was already
deployed. A mitigation that adds capacity has no such natural limit, which is
what makes the second bound necessary rather than symmetrical.

#### Scenario: An application that would exceed the ceiling is clamped to it
- **GIVEN** a mitigation whose derived magnitude exceeds the tier's ceiling
- **WHEN** it is performed
- **THEN** it is performed at the ceiling, and the result reports the figure it
  reached rather than the one it derived

#### Scenario: A mitigation already at the ceiling is refused
- **GIVEN** a subject already at the ceiling for this kind of mitigation
- **WHEN** the same mitigation is proposed for it
- **THEN** it is refused, the refusal names the bound, and the walk moves on to
  another candidate or escalates

#### Scenario: A state-restoring mitigation is unaffected
- **GIVEN** a mitigation that puts a state back rather than changing a quantity
- **WHEN** it is proposed
- **THEN** only the cap is consulted, and no ceiling is required of it
