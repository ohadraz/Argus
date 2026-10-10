## ADDED Requirements

### Requirement: The double names a person the test staged

The double SHALL answer `users.info` in Slack's shape for a person a test staged
through its control interface, and with Slack's `user_not_found` refusal for
anyone else. A reset SHALL forget every staged person.

#### Scenario: A staged person

- **GIVEN** a person staged with a real name
- **WHEN** `users.info` is called for their id
- **THEN** the double answers with that person, in Slack's shape

#### Scenario: An unstaged person

- **WHEN** `users.info` is called for an id nobody staged
- **THEN** the double refuses with `user_not_found`

### Requirement: The double keeps blocks and updates

The double SHALL keep the `blocks` of every posted message, and SHALL accept
`chat.update` for a message it holds, recording the update so that a test can
read what a message says now.

#### Scenario: A button can be read back

- **WHEN** a message carrying a button is posted
- **THEN** its blocks, and the button in them, are readable from the double

#### Scenario: An update is readable

- **GIVEN** a posted message
- **WHEN** it is updated
- **THEN** the double reports the message's new text and blocks
