# conditional-action-undo

## Purpose

TBD

## Requirements

### Requirement: An undo is conditional on the world still holding what Argus left

The system SHALL restore the state named in an action's undo descriptor only
where the subject still holds the value Argus wrote. Where it holds anything
else, the system SHALL leave it alone and record that it was overridden from
outside.

A blind restore would overwrite a deliberate change made by a human after
Argus acted - and where the undo is being run because that human withdrew the
incident, overwriting them is precisely the thing being withdrawn from.

#### Scenario: The value Argus set is put back

- **GIVEN** an action whose flag still holds the value Argus wrote
- **WHEN** the action is undone
- **THEN** the flag is restored to the state named in the undo descriptor

#### Scenario: A value somebody else changed is left alone

- **GIVEN** an action whose flag now holds a value Argus did not write
- **WHEN** the action is undone
- **THEN** the flag is not written, and the outcome records that it was changed
  from outside

#### Scenario: A subject that cannot be read is not written

- **GIVEN** an action whose subject's current state cannot be read
- **WHEN** the action is undone
- **THEN** nothing is written, and the outcome records that the state could not
  be established

### Requirement: The comparison is against the value written, not the value planned

The check SHALL compare against the value the action actually wrote, taken from
the record made at write time, and SHALL NOT compare against a value decided
when the action was proposed. An action is proposed before the world is read
and written after, and treating the plan as the record would judge the world
against a state it may never have been in.

#### Scenario: An action's record is what it is judged against

- **GIVEN** an action whose subject changed between being proposed and being
  written
- **WHEN** it is undone
- **THEN** the comparison uses the value the write recorded

### Requirement: Every undone action reports which of the three it was

Undoing an action SHALL yield, for each action, one of: restored, left as found
because it was changed from outside, or not established. An undo SHALL NOT
report success where nothing was written.

#### Scenario: A run of actions each report their own outcome

- **GIVEN** an incident with three actions, one still as Argus left it, one
  changed from outside, one unreadable
- **WHEN** they are undone
- **THEN** three outcomes are recorded, one of each, and the incident carries
  all three
