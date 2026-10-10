# slack-communication Specification

## Purpose

Covers where an incident is talked about: the war-room message an accepted
alert opens, the thread its progress updates reply into, the channel message
that announces its end, the delivery of the postmortem the Postmortem agent
wrote, and the rule that a Slack workspace refusing a call never changes an
incident's outcome.
## Requirements
### Requirement: An incident has a war room in Slack
The system SHALL post a message to the configured war-room channel when an
incident is accepted, naming the incident and what was alerted, and SHALL keep
that message as the incident's war room for the rest of its life. Every later
message about the incident SHALL be posted in relation to that message rather
than as a message of its own, so that an incident reads as one conversation.

#### Scenario: An accepted alert opens a war room
- **WHEN** an alert is accepted
- **THEN** a message naming the incident is posted to the war-room channel

#### Scenario: The war room outlives the process that opened it
- **GIVEN** an incident whose war room was opened by one process
- **WHEN** another process posts about that incident
- **THEN** it posts into the same war room, without having been told which one

### Requirement: Updates are posted in the incident's thread
The system SHALL post an incident's progress updates as replies in its war
room's thread. An update SHALL NOT be posted to the channel where a reply is
possible, so that following an incident is a choice a reader makes once rather
than an interruption they receive repeatedly.

#### Scenario: An update replies to the war room
- **GIVEN** an incident with a war room
- **WHEN** an update is posted for it
- **THEN** it appears as a reply in that war room's thread and not as a
  channel message

#### Scenario: An incident without a war room still reports
- **GIVEN** an incident whose war-room message was never posted
- **WHEN** an update is posted for it
- **THEN** the update is posted to the channel, naming the incident, rather
  than being dropped

### Requirement: An incident's end is announced in the channel
The system SHALL post a message to the war-room channel when an incident
reaches a terminal status, naming the status it ended in. The message SHALL be
posted to the channel rather than the thread, because the end of an incident is
addressed to everyone who was not following it.

Where the status is `disproven` the message SHALL say that the alarm's own claim
was not in the window Argus read. A message naming only the status would send a
reader to a service Argus has established is well.

The grounds - which signals were judged and over how long - SHALL be posted in
the incident's thread rather than in the channel, as every other finding's are.
The channel hears an ending and its reason; the thread is where the case for it
is followed.

#### Scenario: A resolved incident is announced
- **GIVEN** an incident that reaches `resolved`
- **WHEN** the walk ends
- **THEN** a message naming the incident and its status is posted to the
  war-room channel

#### Scenario: An escalated incident is announced
- **GIVEN** an incident that reaches `escalated`
- **WHEN** the walk ends
- **THEN** a message naming the incident, its status, and why a human is needed
  is posted to the war-room channel

#### Scenario: A disproven incident is announced as a rule to look at
- **GIVEN** an incident that reaches `disproven`
- **WHEN** the walk ends
- **THEN** a message is posted to the war-room channel naming the incident, its
  status, and that the alarm's own claim was not in the window

#### Scenario: The grounds for the disproof are followed, not announced
- **GIVEN** an incident whose alarm the window contradicted
- **WHEN** the disproof is published
- **THEN** it is posted in the incident's thread, carrying the signals judged
  and the span judged over, and is not posted to the channel

### Requirement: The postmortem is delivered where it can be read
The system SHALL deliver the postmortem document the Postmortem agent produced
to the configured postmortem channel, and the incident's closing message SHALL
link to it. The Postmortem agent SHALL NOT deliver anything: it produces the
document and nothing more.

#### Scenario: A postmortem is posted and linked
- **GIVEN** an incident whose postmortem has been written
- **WHEN** the incident is announced as ended
- **THEN** the postmortem is posted to the postmortem channel, and the closing
  message links to it

#### Scenario: An incident with no postmortem is still announced
- **GIVEN** an incident that ended without a postmortem
- **WHEN** the incident is announced as ended
- **THEN** the closing message is posted, carrying no link

### Requirement: Slack failing does not fail the incident
The system SHALL record a Slack call that was refused or could not be made on
the incident's timeline, and SHALL continue the walk. A failure to communicate
SHALL NOT change an incident's status, and SHALL NOT be raised out of the
Communicator.

#### Scenario: A refused post is recorded and survived
- **GIVEN** a Slack workspace refusing the call
- **WHEN** an update is posted for an incident
- **THEN** the timeline records that the message could not be delivered, and
  the incident continues from the status it held

#### Scenario: An unreachable workspace does not end a walk
- **GIVEN** a Slack workspace that cannot be reached
- **WHEN** an incident is walked from acceptance to a terminal status
- **THEN** the incident reaches that status

### Requirement: An offer to resolve is posted with a button

The system SHALL post an offer to resolve as a reply in the incident's thread,
naming the person it is made to and carrying one button that confirms it. It
SHALL NOT post a person's own message, or Argus's classification of it, back
to Slack.

#### Scenario: The offer carries a button

- **WHEN** a resolution is offered to a person
- **THEN** a reply in the incident's thread names that person and carries a
  confirming button

#### Scenario: A person's words are not echoed

- **WHEN** a person writes in the thread and Argus classifies their message
- **THEN** nothing is posted to Slack for either

### Requirement: An offer is retired once the incident can no longer be resolved

The system SHALL replace each offer's button, when the incident reaches a
status that no longer accepts a resolution (`resolved`, `withdrawn`,
`disproven`) by any channel, with who ended it and through which channel, or
with the status it ended in. An incident that is `mitigated`, `escalated` or
`recommended` still accepts one, so its offers SHALL keep their button. A
refused update SHALL be recorded as a communication failure and SHALL NOT
change the incident.

#### Scenario: Resolved through the offer

- **GIVEN** an offer a person confirmed
- **WHEN** the incident's resolution is relayed
- **THEN** the offer says who resolved it, and carries no button

#### Scenario: Resolved elsewhere

- **GIVEN** an open offer
- **WHEN** the incident is resolved from PagerDuty
- **THEN** the offer says who resolved it and that it was through PagerDuty,
  and carries no button

#### Scenario: Mitigated

- **GIVEN** an open offer
- **WHEN** the incident is mitigated
- **THEN** the offer keeps its button

### Requirement: An expired offer loses its button

The system SHALL, when an offer expires, replace it with a line saying it was
not confirmed in time and that Argus carried on, without the button. A refused
update SHALL be recorded as a communication failure and SHALL NOT change the
incident.

#### Scenario: Not confirmed in time

- **GIVEN** an open offer
- **WHEN** it expires
- **THEN** the offer says it was not confirmed in time and Argus carried on,
  and carries no button

