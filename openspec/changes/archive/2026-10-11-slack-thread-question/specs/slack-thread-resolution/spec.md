## MODIFIED Requirements

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

#### Scenario: A question is recorded and answered

- **WHEN** a person asks a question in the thread
- **THEN** the incident records that the message was classified as a question,
  and the question is answered in the thread

#### Scenario: The model cannot be reached

- **GIVEN** a model call that fails twice
- **WHEN** a message is classified
- **THEN** it is recorded as none of these, and a warning is logged
