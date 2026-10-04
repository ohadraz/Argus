## MODIFIED Requirements

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
