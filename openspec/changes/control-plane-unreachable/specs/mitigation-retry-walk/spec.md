## ADDED Requirements

### Requirement: A candidate may be passed over for a platform rather than judged

The walk SHALL treat a candidate whose action acts through a platform already
found unreachable as passed over: no action SHALL be proposed for it, no attempt
SHALL be recorded against it, and the walk SHALL continue to the next candidate.

This is a third thing, and the two it is not are what makes it worth stating. It
is not a refusal at the gate: the gate judges an action it is shown, and no
action is shown here. It is not a refuted attempt either: nothing was attempted,
so nothing was tested, and a record saying a candidate was refuted would have the
postmortem report that the evidence ruled a cause out when nothing ruled it out.

#### Scenario: A passed-over candidate leaves no attempt behind
- **GIVEN** a walk in which the platform has been found unreachable
- **WHEN** the next candidate acts through that platform
- **THEN** no action is proposed for it and no attempt is recorded against it

#### Scenario: A passed-over candidate is not recorded as refuted
- **GIVEN** a candidate passed over for an unreachable platform
- **WHEN** the incident's record is read
- **THEN** that candidate's hypothesis is not marked refuted

#### Scenario: The walk continues past it
- **GIVEN** a candidate passed over for an unreachable platform, and a further
  candidate on a reachable platform
- **WHEN** the walk continues
- **THEN** an action is proposed and taken for that further candidate
