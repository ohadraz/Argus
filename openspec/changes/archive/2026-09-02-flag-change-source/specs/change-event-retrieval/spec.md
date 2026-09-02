## ADDED Requirements

### Requirement: The change channel reads every system that records a change

The system SHALL offer the Investigator one change history per window, assembled from
every system that records a change to what the service does - a deploy history and the
flag provider's audit log. Each change SHALL carry the kind of change it was, so that a
deploy and a flag toggle remain distinguishable to the model weighing one against the
other.

Where a provider serves its history only to a credential that can also write, the system
SHALL read that history through the write tier rather than granting the read tier such a
credential. The read process SHALL hold no credential that can change state.

#### Scenario: A flag toggle is offered as a change
- **GIVEN** a flag the provider recorded as switched inside the window
- **WHEN** the change channel is read
- **THEN** a change of kind flag-toggle is offered, naming the flag verbatim

#### Scenario: A deploy is still offered when nothing was toggled
- **GIVEN** a deploy inside the window and no recorded flag change
- **WHEN** the change channel is read
- **THEN** the deploy is offered unchanged

#### Scenario: Both histories arrive as one
- **GIVEN** a deploy and a flag toggle recorded at different moments in the window
- **WHEN** the change channel is read
- **THEN** both are offered in the order they occurred

### Requirement: A change is stated in terms the model and the mitigation can both act on

A flag toggle SHALL state which flag changed and in which direction it moved, and SHALL
carry the actor the provider attributed it to when the provider names one. The direction
SHALL be stated in words rather than left implicit, since a flag is put back by moving it
the other way and the two directions are both ordinary.

#### Scenario: The direction is stated
- **GIVEN** a flag the provider recorded as switched off
- **WHEN** the change is offered
- **THEN** its summary says the flag was switched off

#### Scenario: The actor survives
- **GIVEN** a flag change the provider attributes to a named actor
- **WHEN** the change is offered
- **THEN** it carries that actor, so an action Argus took is distinguishable from a human's

### Requirement: The window bounds every source

The system SHALL apply both ends of the requested window to every change source,
including one whose provider accepts only a lower bound. A change recorded after the
window closes SHALL NOT be offered.

#### Scenario: A toggle after the window closes is not offered
- **GIVEN** a flag toggle recorded after the window's end
- **WHEN** the change channel is read
- **THEN** it is not among the changes offered

#### Scenario: The flag history is asked about the window it was given
- **GIVEN** a window starting at a named instant
- **WHEN** the change channel is read
- **THEN** the flag history is asked for changes since that instant

## MODIFIED Requirements

### Requirement: An unreachable change source is an error, not an empty answer
The system SHALL fail loudly when any change source cannot be reached or answers with an
error, and SHALL NOT report "no changes" in that case. Silence and absence are opposite
facts, and reporting one as the other would let an outage become evidence that nothing
changed. This SHALL hold for every source the channel reads, so that adding one cannot
quietly turn a failure into an empty history.

#### Scenario: An unreachable source raises rather than returning nothing
- **GIVEN** a change source that cannot be reached
- **WHEN** change events are requested
- **THEN** the request fails with an error naming the unreachable source, and
  no empty result is produced

#### Scenario: An error response is not mistaken for an empty history
- **GIVEN** a change source answering with an error status
- **WHEN** change events are requested
- **THEN** the request fails, and the failure is distinguishable from a window
  that genuinely contained no changes

#### Scenario: The flag history cannot be read
- **GIVEN** a flag provider that cannot be reached
- **WHEN** the change channel is read
- **THEN** the failure reaches the caller rather than an empty history
