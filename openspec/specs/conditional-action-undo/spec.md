# conditional-action-undo

## Purpose

TBD

## Requirements

### Requirement: An undo is conditional on the world still holding what Argus left

The system SHALL restore the state named in an action's undo descriptor only
where nothing has changed the subject since Argus wrote it. Where anything has,
the system SHALL leave it alone and record that it was overridden from outside.

The question SHALL be answered from the provider's record of changes - who
changed what, and when - and SHALL NOT be answered by comparing the subject's
current value against the value Argus wrote. A provider serves current state
from a cache it refreshes on its own schedule, so a comparison of values reports
that nobody has been in there for as long as that cache is stale. Nobody in
production waits for a cache, and the change being overwritten in that window is
a deliberate human one.

A blind restore would overwrite a deliberate change made by a human after
Argus acted - and where the undo is being run because that human withdrew the
incident, overwriting them is precisely the thing being withdrawn from.

#### Scenario: An untouched flag is put back

- **GIVEN** an action whose flag nothing has changed since Argus wrote it
- **WHEN** the action is undone
- **THEN** the flag is restored to the state named in the undo descriptor

#### Scenario: A flag somebody else changed is left alone

- **GIVEN** an action whose flag somebody other than Argus changed after Argus
  wrote it
- **WHEN** the action is undone
- **THEN** the flag is not written, and the outcome records that it was changed
  from outside

#### Scenario: A change that was made and taken back is still a change

- **GIVEN** an action whose flag somebody switched and then switched back, so
  that it now holds exactly what Argus wrote
- **WHEN** the action is undone
- **THEN** the flag is left as found, because somebody has been in there since
  Argus wrote it

#### Scenario: A history that cannot be read is not written over

- **GIVEN** an action whose flag's change history cannot be read
- **WHEN** the action is undone
- **THEN** nothing is written, and the outcome records that the state could not
  be established

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

### Requirement: The record is asked from the moment Argus wrote

The undo SHALL ask the provider what changed from the moment Argus's own write
was recorded, using the time the provider recorded it rather than a time Argus
took from its own clock. The undo descriptor SHALL carry that moment, written
into it by the call that made the change, since that call is the only thing that
knows when the provider recorded it.

An undo descriptor that carries no such moment SHALL report that the state could
not be established. Guessing from the current value is the failure this
requirement exists to remove, and a descriptor written before this rule existed
is not evidence that nobody has been in there.

Changes the provider attributes to Argus itself SHALL NOT count as somebody
else's. Where the provider attributes nothing - a deployment in which Argus and
its operators share one credential - no change can be told from another, and the
undo SHALL leave the flag as found rather than act on an attribution it does not
have.

#### Scenario: Only changes after Argus's write are considered

- **GIVEN** a flag somebody changed before Argus wrote to it and nobody has
  changed since
- **WHEN** the action is undone
- **THEN** the flag is restored, because the earlier change is not evidence of
  anybody being in there after Argus

#### Scenario: Argus's own write is not read as somebody else's

- **GIVEN** an action whose only recorded change since Argus wrote is Argus's
  own write
- **WHEN** the action is undone
- **THEN** the flag is restored

#### Scenario: A descriptor with no recorded moment is not acted on

- **GIVEN** an action whose undo descriptor does not say when Argus wrote
- **WHEN** the action is undone
- **THEN** nothing is written, and the outcome records that the state could not
  be established
