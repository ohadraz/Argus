## ADDED Requirements

### Requirement: An undo that restores more than one thing restores all of it
The system SHALL allow a generic mitigation's undo descriptor to record more
than one piece of prior state, and SHALL restore every piece when the mitigation
is undone. An action that had to change a second thing in order to change the
first has left two changes behind, and an undo that put back only the one the
action was named for would leave the environment in a state Argus could not
account for - which is the condition the descriptor exists to prevent.

#### Scenario: Every recorded piece of prior state is restored
- **GIVEN** a performed mitigation whose undo descriptor records two pieces of
  prior state
- **WHEN** it is undone
- **THEN** both are restored

#### Scenario: A partial restore is reported rather than counted as undone
- **GIVEN** a performed mitigation whose undo restores one piece of state and
  fails on another
- **WHEN** the undo is attempted
- **THEN** it is recorded as not fully undone, naming what remains changed, and
  the incident is escalated rather than closed
