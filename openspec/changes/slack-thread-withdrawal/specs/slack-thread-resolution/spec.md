## MODIFIED Requirements

### Requirement: A walk waits for a person's answer

The system SHALL, once a person has written in an incident's thread while its
walk runs, start no new step of that walk until each such message is answered:
classified as anything but a resolution or a request to stand down; or offered,
and the offer pressed; or offered, and the incident no longer
accepting what the offer offers; or 5 minutes past the message on the stack's
clock. A step already running SHALL finish. A press SHALL end the walk as it
does from any other channel. At 5 minutes, an offer still standing SHALL
expire, the expiry SHALL be recorded on the incident, and the walk SHALL carry
on. An incident whose walk is not running SHALL wait for nothing, and its
offers SHALL NOT expire.

#### Scenario: The person confirms in time

- **GIVEN** a walk that has just finished a step
- **AND** a person's message classified as a resolution, offered to them
- **WHEN** they press the button within 5 minutes
- **THEN** no further step starts, and the incident is resolved

#### Scenario: Nobody confirms

- **GIVEN** a walk waiting on an offer
- **WHEN** 5 minutes pass since the message, with no press
- **THEN** the offer expires, the expiry is on the incident, and the walk
  starts its next step

#### Scenario: A message that is not a resolution

- **GIVEN** a walk waiting on a person's message
- **WHEN** the message is classified as a question
- **THEN** the walk starts its next step

#### Scenario: A message not yet classified

- **GIVEN** a walk that has just finished a step
- **AND** a person's message stored but not yet classified
- **THEN** the walk starts no new step until it is

#### Scenario: A request to stand down is waited on

- **GIVEN** a walk that has just finished a step
- **AND** a person's message classified as a request to stand down, offered to
  them
- **WHEN** they press the button within 5 minutes
- **THEN** no further step starts, and the incident is withdrawn

#### Scenario: An offer the incident no longer accepts is not waited on

- **GIVEN** a withdrawal offer made while Code-Fix was running
- **WHEN** Code-Fix finishes and leaves the incident mitigated
- **THEN** the walk does not wait on the offer, and starts its next step
