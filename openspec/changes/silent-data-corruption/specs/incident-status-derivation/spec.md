## ADDED Requirements

### Requirement: An action named and not taken is derived as `RECOMMENDED`, wherever the walk got to afterwards

The system SHALL derive `RECOMMENDED` from a state in which an action was named
and refused as unconfirmable, and SHALL derive it in preference to the status the
rest of that walk would otherwise produce.

An incident of this kind still goes on to Code-Fix - the fault is in the code
whether or not anybody may act on it - so it passes through `fixing` and reaches
the end of the graph the same way a mitigated incident does. The derivation must
therefore be decided by the refusal rather than by where the walk stopped, or the
incident would report itself escalated and the named action would be lost.

`RECOMMENDED` SHALL be terminal, alongside `mitigated`, `resolved`, `escalated`
and `withdrawn`: as far as Argus can take it, with something owed that is a
person's to do.

#### Scenario: A walk that went on to Code-Fix still reports the recommendation
- **GIVEN** an incident whose action was refused as unconfirmable and which then
  proposed a fix
- **WHEN** its status is derived
- **THEN** it is `RECOMMENDED`

#### Scenario: The function stays total over the new state
- **WHEN** a status is derived for every state the graph can now produce
- **THEN** each one yields a status, with no state falling through

#### Scenario: A withdrawal still wins
- **GIVEN** a `RECOMMENDED` incident a human has withdrawn
- **WHEN** its status is derived
- **THEN** it is `WITHDRAWN`
