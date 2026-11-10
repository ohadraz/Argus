# executive-synopsis-slack Specification

## Purpose
How the executive synopsis reaches the people it is for: posted once to each
configured Slack id, a member's as a direct message and a channel's in the
channel, and never in the war room, an incident's thread or the postmortem
channel, since it states what the response cost.
## Requirements
### Requirement: The synopsis is posted to each configured Slack id
The system SHALL post each incident's executive synopsis once to each Slack id
in one configured list: a member's id as a direct message, a channel's id in
that channel.

#### Scenario: Two members and a channel
- **GIVEN** two member ids and a channel id configured
- **WHEN** an incident's synopsis is written with an overview
- **THEN** each member gets one direct message and the channel one message

#### Scenario: Nothing configured
- **GIVEN** no Slack id configured
- **WHEN** an incident's synopsis is written
- **THEN** nothing is posted for it

### Requirement: The message is the synopsis and its link, with no file
The Slack message SHALL carry the overview, every other part of the synopsis in
order, and the full postmortem's address where one is configured. It SHALL
carry no file.

#### Scenario: Every part, in order
- **GIVEN** a synopsis with something in every part
- **WHEN** it is posted to Slack
- **THEN** the message says each part, in the order the synopsis reads

### Requirement: Said only to the people it is for
The synopsis SHALL be posted only to the configured members and channel: never
to the war room, an incident's thread or the postmortem channel.

#### Scenario: The war room hears nothing of it
- **WHEN** an incident's synopsis is posted
- **THEN** nothing about it is posted to the war room, the incident's thread or
  the postmortem channel

### Requirement: No overview, no message
The system SHALL post nothing for a synopsis without an overview. The timeline
already says it was withheld.

#### Scenario: A withheld synopsis posts nothing
- **GIVEN** an incident whose overview was given up
- **WHEN** the chat relay reaches it
- **THEN** nothing is posted, and the relay moves past it

### Requirement: What Slack did not take is recorded
A post Slack refuses SHALL be recorded where the chat relay records any line
that did not land, naming the member or channel, and SHALL NOT stop the posts to
the others.

#### Scenario: A channel the app was not invited to
- **GIVEN** a configured channel the app is not a member of, and one member
- **WHEN** the synopsis is posted
- **THEN** the member gets it, and the channel's refusal is recorded

