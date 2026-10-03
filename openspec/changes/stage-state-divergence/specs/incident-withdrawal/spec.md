## MODIFIED Requirements

### Requirement: The timeline says what was withdrawn and what was undone

The system SHALL record on the incident's timeline that it was withdrawn, what
Argus had done by that point, and one entry per undo step attempted, each saying
whether the state was put back, was found already changed by somebody else, or
needed no putting back. A human reading a withdrawn incident SHALL be able to tell
what state Argus left behind without inspecting the environment.

The third case arrives with the first action whose change is a removal. Discarding
a cache entry leaves nothing to restore - the entry was a copy of data that never
moved, and the service has already rebuilt whichever copies anybody has asked for -
so a withdrawal there makes no write and must say that it made none. A timeline
silent about it would read as an undo that was skipped.

#### Scenario: An undo that succeeded is narrated

- **GIVEN** a withdrawn incident in which Argus had changed a flag
- **WHEN** the incident's timeline is read
- **THEN** it records the change Argus made and that the flag was put back

#### Scenario: An undo that found an outside change is narrated

- **GIVEN** a withdrawn incident in which Argus had changed a flag that somebody
  then changed again
- **WHEN** the incident's timeline is read
- **THEN** it records that the flag was left as found because it no longer held
  what Argus set

#### Scenario: A withdrawal with nothing to undo says so

- **GIVEN** an incident withdrawn before Argus took any action
- **WHEN** the incident's timeline is read
- **THEN** it records the withdrawal and that nothing had been changed

#### Scenario: An action that needed no undo is narrated as such

- **GIVEN** a withdrawn incident in which Argus had discarded cache entries
- **WHEN** the incident's timeline is read
- **THEN** it records the discard, that nothing was written back, and that the
  entries the service needed have been rebuilt from data that never changed
