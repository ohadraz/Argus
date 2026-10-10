# slack-thread-resolution Specification

## Purpose
TBD - created by archiving change slack-thread-resolution. Update Purpose after archive.
## Requirements
### Requirement: Argus ingests a person writing in an incident's thread

The system SHALL accept Slack's message events at a signed endpoint and SHALL
record each new reply a person writes in an incident's Slack thread on that
incident, acknowledging within Slack's three seconds without a model call or a
Slack read. It SHALL ignore a top-level message, a bot's message, an edit, a
deletion, any other message subtype, and a reply in a thread no incident holds.
A delivery Slack repeats SHALL be recorded once.

#### Scenario: A reply in the thread is recorded

- **GIVEN** an incident whose war room was opened in Slack
- **WHEN** a person replies in that thread
- **THEN** the incident records that the person wrote, with their Slack id and
  their words

#### Scenario: A repeated delivery is recorded once

- **GIVEN** a reply already recorded
- **WHEN** Slack delivers the same message again
- **THEN** nothing more is recorded

#### Scenario: Argus does not ingest itself

- **WHEN** a message posted by a bot arrives
- **THEN** nothing is recorded

#### Scenario: A thread no incident holds

- **WHEN** a reply arrives in a thread no incident holds
- **THEN** nothing is recorded, and the delivery is acknowledged

### Requirement: Only a delivery Slack signed is believed

The system SHALL verify Slack's signature over the raw body and its timestamp on
every event and interaction delivery, and SHALL refuse one whose signature does
not match, whose timestamp is more than five minutes from the system's clock,
or that arrives while no signing secret is configured. Where Slack is not
configured at all, both endpoints SHALL answer that they do not exist. The
system SHALL answer Slack's URL verification with its challenge.

#### Scenario: A forged delivery

- **WHEN** a delivery arrives whose signature does not match
- **THEN** it is refused, and nothing is recorded

#### Scenario: A replayed delivery

- **WHEN** a correctly signed delivery arrives with a timestamp six minutes old
- **THEN** it is refused

#### Scenario: Slack verifies the URL

- **WHEN** Slack sends a signed URL verification
- **THEN** the challenge is answered

### Requirement: Every message a person writes is classified for what they meant

The system SHALL classify each recorded message as one meaning: that the incident
is resolved, a question, new information, a request to stand down and leave
the incident to the person, or none of these. It SHALL record the
meaning on the incident. Classifying SHALL happen outside the delivery, and a
message that cannot be classified after one retry SHALL be recorded as none of these,
with a warning.

#### Scenario: A resolution is recognised

- **WHEN** a person writes that they have resolved the incident
- **THEN** the incident records that the message was classified as a resolution

#### Scenario: A question is recorded and not acted on

- **WHEN** a person asks a question in the thread
- **THEN** the incident records that the message was classified as a question, and
  nothing else happens

#### Scenario: The model cannot be reached

- **GIVEN** a model call that fails twice
- **WHEN** a message is classified
- **THEN** it is recorded as none of these, and a warning is logged

### Requirement: A resolution is offered before it is made

The system SHALL, when a message is classified as a resolution and the incident still
accepts one, reply in the thread asking the person who wrote it to confirm,
with a button. It SHALL name that person by their Slack name, read when the
offer is made. Where the name cannot be read, it SHALL still make the offer,
addressed to whoever wrote the message, and a resolution confirmed through it
SHALL credit the person by their Slack id. When the incident has already ended, no offer
SHALL be made.

#### Scenario: An offer is made

- **GIVEN** an open incident
- **WHEN** a person's message is classified as a resolution
- **THEN** a reply in the thread asks that person to confirm, with a button

#### Scenario: No offer on an ended incident

- **GIVEN** an incident that has already ended
- **WHEN** a person's message is classified as a resolution
- **THEN** no offer is made

### Requirement: Only the person who said it can confirm

The system SHALL resolve the incident when the person an offer was made to
presses its button, as a report through Slack, crediting that person by the name
the offer carried, or by their Slack id where it carried none, and with their message, verbatim, as the note. A press by
anyone else SHALL change nothing. A press on an incident that has already ended
SHALL change nothing. A press on an offer that has expired SHALL change nothing.

#### Scenario: The person confirms

- **GIVEN** an offer made to a person on an open incident
- **WHEN** that person presses the button
- **THEN** the incident is resolved, credited to that person, through Slack,
  with their message as the note

#### Scenario: Someone else presses

- **GIVEN** an offer made to one person
- **WHEN** another person presses the button
- **THEN** nothing changes

#### Scenario: A press after the incident ended

- **GIVEN** an offer on an incident that has since ended
- **WHEN** its person presses the button
- **THEN** nothing changes

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

### Requirement: A resolution from Slack leaves Argus's changes in place

A resolution reported through Slack SHALL end the walk exactly as a resolution
reported through any other channel does: the report is the fact, Argus's own
changes stay as they are, and the postmortem credits the person through Slack.

#### Scenario: Resolved after a mitigation

- **GIVEN** an incident whose flag Argus turned off
- **WHEN** a person resolves it from its Slack thread
- **THEN** the incident is resolved, the flag stays off, and the postmortem
  names the person, Slack and their words

