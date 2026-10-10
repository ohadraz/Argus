# chat-platform-port Specification

## Purpose
TBD - created by archiving change slack-thread-resolution. Update Purpose after archive.
## Requirements
### Requirement: The chat platform sits behind a port

The system SHALL reach the chat platform's inbound deliveries and its people,
and SHALL post and rewrite what it says there, through a port named for the
role and split by direction, returning Argus's own values. Only the platform's
adapter SHALL know the platform's envelopes, headers, field names, blocks or
methods, and only the composition roots of the web application, the intent agent
and the Communicator SHALL build it.
Without a configured platform, no adapter SHALL be built.

#### Scenario: A delivery is read in Argus's words

- **WHEN** the adapter reads a signed reply in a thread
- **THEN** it answers with the thread, the message, the person's id and their
  words, and nothing in Slack's shape

#### Scenario: An interaction that is not Argus's

- **WHEN** the adapter reads a button press whose action Argus did not post
- **THEN** it answers that the delivery is irrelevant

#### Scenario: An offer is posted in Argus's words

- **WHEN** the Communicator posts a line carrying an offer about a person's
  message
- **THEN** the adapter draws the button, naming that message, and the
  Communicator handles no part of the platform's shape

### Requirement: A person is named by the platform

The port SHALL name a person from their platform id: Slack's real name, else
their display name. When the platform does not know the person, or cannot be
reached, it SHALL answer that it could not say, and SHALL NOT raise.

#### Scenario: A person with a real name

- **GIVEN** a Slack user with a real name and a display name
- **WHEN** they are named
- **THEN** the real name is answered

#### Scenario: An unknown person

- **WHEN** a person Slack does not know is named
- **THEN** the answer is that it could not say

