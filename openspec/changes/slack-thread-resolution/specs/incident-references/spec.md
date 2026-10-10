## ADDED Requirements

### Requirement: An incident's chat thread is one of its references

The system SHALL record the chat thread an incident is told in as one of the
incident's references, keyed by the channel and the thread's own identity, and
SHALL hold at most one thread per incident per channel. A second thread
recorded for the same incident and channel SHALL record nothing and leave the
first standing. A message received in a thread SHALL find its incident through
this reference.

#### Scenario: The first thread stands

- **GIVEN** an incident with a thread recorded in a channel
- **WHEN** a second thread is recorded for that incident in that channel
- **THEN** the first remains the incident's thread there

#### Scenario: A reply finds its incident

- **GIVEN** an incident with a thread recorded
- **WHEN** it is looked up by that channel and thread
- **THEN** that incident is found

### Requirement: A reference can be claimed once

The system SHALL record a reference and say whether this recording was the one
that wrote it, so that a delivery repeated by its sender is acted on once.

#### Scenario: A second claim

- **GIVEN** a reference already recorded
- **WHEN** it is claimed again
- **THEN** the claim reports that nothing was written
