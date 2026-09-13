## MODIFIED Requirements

### Requirement: The document is checked once and then handed off regardless
The system SHALL check its own document for missing required fields, and where
any are missing SHALL ask the model once more, naming them. Whatever comes back
SHALL be written, with the document recording whether it is complete. There
SHALL be no further attempt. The document SHALL then be handed to the
Communicator for delivery: the Postmortem agent SHALL produce the document and
SHALL NOT send it anywhere, so that what a postmortem says and where it is read
stay separate concerns.

#### Scenario: A complete document is written without a second call
- **WHEN** the first answer carries every required field
- **THEN** the document is written and marked complete, with no second model
  call

#### Scenario: A second incomplete answer is still written
- **GIVEN** a first answer missing required fields
- **WHEN** the second answer is also missing fields
- **THEN** the document is written with what is present and marked incomplete

#### Scenario: The written document is handed over for delivery
- **GIVEN** a written postmortem
- **WHEN** the incident ends
- **THEN** the Communicator delivers that document, and the Postmortem agent
  makes no call to any destination
