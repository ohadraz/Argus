# corruption-mitigation-choice

## Purpose
Choosing the action that answers silent data corruption. Every other mode names
its action, because the mode itself says what kind of thing went wrong; this one
says only that the data is wrong, and a flag, a deployment, a migration or a
person at a console can each have made it so. So the mode chooses the family of
answers - undo the change - and the change recorded at the incident's onset
chooses which: a flag change is answered by putting the flag back, a deployment
by returning it. Where the record holds neither, nothing is proposed and the
incident escalates, because a recommendation is read and acted on by a person,
and a rollback recommended with no deployment behind it sends somebody to undo
work that did not cause the fault. The choice is made from the flag and deploy
histories read once at the top of the round, so the candidate chosen and the
action proposed are reasoned from one account of what changed.

## Requirements

### Requirement: Silent data corruption is answered by undoing the change the record names

The system SHALL choose the mitigation for silent data corruption from the change
recorded at the incident's onset: a flag change is answered by putting the flag
back, and a deployment by returning the deployment. Where the record holds
neither, the system SHALL propose nothing.

Every other mode determines its action, because the mode is itself a statement
about what kind of thing went wrong. This one does not: it says the data is
wrong, and a flag, a deployment, a migration or a person at a console can each
have made it so. So the mode chooses the family of answers - undo the change -
and the record chooses which.

Nothing rather than a guess where the record holds no change, because a
recommendation is still read and acted on by a person. A rollback recommended
with no deployment behind it sends somebody to undo a week of somebody else's
work for a fault it did not cause.

#### Scenario: A flag change at the onset is answered by the flag revert
- **GIVEN** a candidate naming silent data corruption, and a flag history holding
  the change the candidate names
- **WHEN** Mitigation proposes an action
- **THEN** it is the flag revert, exactly as before this choice existed

#### Scenario: A deployment at the onset is answered by the rollback
- **GIVEN** a candidate naming silent data corruption, an empty flag history, and
  a deploy history holding a deployment
- **WHEN** Mitigation proposes an action
- **THEN** it is the rollback of the alerting service's deployment

#### Scenario: Neither change recorded proposes nothing
- **GIVEN** a candidate naming silent data corruption, and empty flag and deploy
  histories
- **WHEN** Mitigation proposes an action
- **THEN** it proposes none

#### Scenario: A flag the candidate names wins over a deployment beside it
- **GIVEN** a candidate naming silent data corruption and a flag, and histories
  holding both that flag's change and a deployment
- **WHEN** Mitigation proposes an action
- **THEN** it is the flag revert

### Requirement: The deploy history is read once per round, beside the flag history

The system SHALL read the deploy history at the top of each round, anchored on
the same minute as the flag history, and SHALL hand both to every caller that
asks which action answers a candidate.

The flag history is read there for a reason that holds for this one too: the
candidate chosen and the action proposed must be reasoned from one account of
what changed. A deploy history that could not be read SHALL reach Mitigation as
unread rather than as empty, and no strategy that ignores it SHALL change its
answer because of it.

#### Scenario: Both callers see the same deployments
- **GIVEN** a round whose deploy history holds a deployment
- **WHEN** the candidates are ranked and an action is later proposed
- **THEN** both were asked with that same deployment

#### Scenario: An unread deploy history proposes no rollback for corruption
- **GIVEN** a candidate naming silent data corruption, an empty flag history, and
  a deploy history that could not be read
- **WHEN** Mitigation proposes an action
- **THEN** it proposes none

#### Scenario: Other modes are unaffected by the deploy history
- **GIVEN** a candidate naming any mode other than silent data corruption
- **WHEN** Mitigation proposes an action with and without a deployment recorded
- **THEN** the two proposals are the same
