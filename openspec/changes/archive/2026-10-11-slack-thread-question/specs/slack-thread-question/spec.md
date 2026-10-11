## ADDED Requirements

### Requirement: A question is answered in its thread

The system SHALL answer each message classified as a question, and SHALL post
the answer as a reply in the incident's thread and on its timeline. A question
SHALL be answered whatever the incident's status, including after it has
ended. Answering SHALL NOT change the incident, the walk or any offer.

#### Scenario: A question asked during an incident

- **GIVEN** an incident with a walk under way
- **WHEN** a person asks a question in its thread
- **THEN** an answer is posted as a reply in that thread, and is on the
  incident's timeline

#### Scenario: A question asked after the incident ended

- **GIVEN** a resolved incident
- **WHEN** a person asks a question in its thread
- **THEN** an answer is posted in that thread, and the incident stays resolved

### Requirement: An answer comes from the incident's record

The system SHALL answer a question from the incident's recorded timeline alone
- every recorded event, said as the timeline says it - and the question. It
SHALL read nothing else to answer, and SHALL say so plainly when the timeline
does not hold the answer rather than give one it does not support. An answer
SHALL NOT promise or describe an action as one Argus will take.

#### Scenario: The record holds the answer

- **GIVEN** an incident whose timeline records that a flag was reverted
- **WHEN** a person asks what Argus did
- **THEN** the answer is given from the timeline

#### Scenario: The record does not hold the answer

- **WHEN** a person asks something the timeline says nothing about
- **THEN** the answer says the record does not hold it

### Requirement: A question that cannot be answered is still acknowledged

The system SHALL try a question at most twice. A question that cannot be
answered after that SHALL be recorded as understood and answered with a line
saying Argus could not answer it, with a warning.

#### Scenario: The model cannot be reached

- **GIVEN** a model call that fails twice
- **WHEN** a question is answered
- **THEN** the thread is told Argus could not answer it, and a warning is
  logged
