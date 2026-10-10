# slack-thread-withdrawal Specification

## Purpose
TBD - created by archiving change slack-thread-withdrawal. Update Purpose after archive.
## Requirements
### Requirement: A request to stand down is offered before it is made

The system SHALL, when a message is classified as a request to stand down and
the incident can still be withdrawn, reply in the thread asking the person who
wrote it to confirm, with a button. The reply SHALL say that confirming stops
Argus and puts back what it changed. It SHALL name that person by their Slack
name, read when the offer is made, and where the name cannot be read it SHALL
still make the offer, addressed to whoever wrote the message. When the incident
has already ended, no offer SHALL be made.

#### Scenario: An offer is made

- **GIVEN** an incident Argus is working on
- **WHEN** a person's message is classified as a request to stand down
- **THEN** a reply in the thread asks that person to confirm, says that Argus
  will stop and put back what it changed, and carries a button

#### Scenario: No offer on an ended incident

- **GIVEN** an incident that has already ended
- **WHEN** a person's message is classified as a request to stand down
- **THEN** no offer is made

### Requirement: Only the person who asked can confirm the withdrawal

The system SHALL withdraw the incident when the person a withdrawal offer was
made to presses its button, as a withdrawal through Slack, crediting that
person by the name the offer carried, or by their Slack id where it carried
none, with their message, verbatim, as the note. A press by anyone else SHALL
change nothing. A press on an offer that has expired SHALL change nothing. A
press on an incident that has since ended SHALL change nothing.

#### Scenario: The person confirms

- **GIVEN** a withdrawal offer made to a person on an incident Argus is working
  on
- **WHEN** that person presses the button
- **THEN** the incident is withdrawn, credited to that person, through Slack,
  with their message as the note

#### Scenario: Someone else presses

- **GIVEN** a withdrawal offer made to one person
- **WHEN** another person presses the button
- **THEN** nothing changes

#### Scenario: A press after the incident ended

- **GIVEN** a withdrawal offer on an incident that has since been mitigated
- **WHEN** its person presses the button
- **THEN** nothing changes, and nothing Argus did is undone

### Requirement: A withdrawal from Slack unwinds as any withdrawal does

A withdrawal through Slack SHALL end the walk exactly as a withdrawal through
any other channel does: no further step, Argus's own changes put back where
they still hold what Argus set, and the timeline saying who withdrew it,
through Slack, and what was undone.

#### Scenario: Withdrawn before any action

- **GIVEN** an incident whose investigation has finished and on which Argus
  has changed nothing
- **WHEN** a person withdraws it from its Slack thread
- **THEN** the incident is withdrawn, no action is taken, no fix is looked
  for, no postmortem is written, and the timeline names the person and Slack
  and says nothing had been changed

