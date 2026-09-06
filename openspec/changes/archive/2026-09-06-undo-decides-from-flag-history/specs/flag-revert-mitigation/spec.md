## MODIFIED Requirements

### Requirement: A refuted action is undone

Where an action's verdict is `refuted`, the system SHALL restore the state
recorded in that action's undo descriptor before the incident proceeds, and
SHALL do so only where nothing has changed the flag since Argus wrote it, judged
from the provider's record of changes rather than from the flag's current value.
An action that did not resolve the symptom was taken on a hypothesis the evidence
has not borne out, and leaving its change in place would mean production state
was altered for a cause that was not the cause, with no one told - but a flag
somebody has changed since is no longer Argus's to put back, and overwriting it
would replace a deliberate human change with a state nobody chose.

The refuted path is where this matters most quietly. A withdrawal has a person
watching; a refutation happens in the middle of a walk with nobody looking, and
an undo that overwrote somebody there would be discovered later or not at all.

#### Scenario: A refuted flag revert puts the flag back
- **GIVEN** a flag was changed and the service's minutes after it still depart
  from the baseline
- **WHEN** the verdict is formed
- **THEN** the flag holds the state named in the undo descriptor again, as the
  provider reports it

#### Scenario: A confirmed action is left in place
- **GIVEN** a flag was changed and the service recovered
- **WHEN** the verdict is formed
- **THEN** the flag keeps the state the action put it in

#### Scenario: A flag changed from outside is not overwritten by the undo
- **GIVEN** a refuted action whose flag somebody changed after Argus wrote it
- **WHEN** the undo runs
- **THEN** the flag is left as found, and the incident records that it was
  changed from outside rather than put back

#### Scenario: A flag changed from outside a moment ago is still not overwritten
- **GIVEN** a refuted action whose flag was changed from outside so recently
  that the provider still evaluates the value Argus wrote
- **WHEN** the undo runs
- **THEN** the flag is left as found, because the change is in the provider's
  record whether or not its evaluation has caught up

#### Scenario: A failed restore escalates rather than passing quietly
- **GIVEN** a refuted action whose recorded state cannot be restored
- **WHEN** the restore is attempted
- **THEN** the incident escalates, carrying both the action taken and the failure
  to restore it
