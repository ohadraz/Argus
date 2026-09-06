## ADDED Requirements

### Requirement: A case leaves no walk of its own still running

Each end-to-end case SHALL withdraw the incident it started and SHALL wait for
its run to be settled before the next case begins. A case ends when its own
assertion holds, which is earlier than the walk it started ends, and a walk
outliving its case reaches into the next one - reading the flags that case
arranged and consuming the model answers seeded for it.

#### Scenario: A case that asserted early does not leak its walk

- **GIVEN** a case whose assertion holds while its incident is still being
  walked
- **WHEN** the case ends
- **THEN** the incident is withdrawn and no walk is running when the next case
  begins

#### Scenario: The next case's seeded answers are its own

- **GIVEN** two cases run in sequence, each seeding the model answers for its own
  scenario
- **WHEN** the second case runs
- **THEN** every answer it receives is one it seeded, and no call is left
  unanswered

### Requirement: A case leaves no rows behind

Each end-to-end case SHALL empty the database of everything it wrote once its
run has settled - incidents, runs, hypotheses, actions, timeline events,
incident events, replay entries and postmortems. What to empty SHALL be asked of
the database rather than listed, so a table added later does not silently leak
its rows into every later case.

The suite SHALL NOT drop the database or its schema: a case did not bring the
stack up and does not take it down.

#### Scenario: The next case starts against an empty history

- **GIVEN** a case that ran an incident to completion
- **WHEN** the next case begins
- **THEN** no incident, hypothesis, action, timeline event, incident event,
  replay entry or postmortem from the earlier case remains

#### Scenario: A new table does not have to be remembered

- **GIVEN** a table added to the schema after this fixture was written
- **WHEN** a case ends
- **THEN** that table is emptied too, with no change to the fixture

#### Scenario: The stack survives the case

- **GIVEN** a case that has ended
- **WHEN** the next case begins
- **THEN** the database, its schema and the worker are the ones the stack
  started, not ones the case brought up
