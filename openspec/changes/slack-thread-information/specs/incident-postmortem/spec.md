## ADDED Requirements

### Requirement: The document says what people told Argus

The system SHALL report, for every lead written in the incident's thread, who
wrote it - by the name the chat platform gives them, or by its id for them
where it gives none - their words, the standing the Investigator gave it and its reason, or
that it was never weighed, all taken from the incident record. The model SHALL
say, for each lead, in one sentence, whether it changed what was done. A
submission that leaves a lead without that sentence SHALL be refused, as a
missing field is. An incident with no leads SHALL report none, and the model
SHALL be asked for nothing about them.

#### Scenario: A lead that was acted on

- **GIVEN** an incident whose first action was on a change a lead named, the
  lead weighed supported
- **WHEN** the postmortem is written
- **THEN** it names the person, quotes the lead, gives its standing and reason,
  and says whether the lead changed what was done

#### Scenario: A lead left out

- **GIVEN** an incident with two leads
- **WHEN** the model submits a document that says what one of them changed
- **THEN** the submission is refused, naming the lead left out

#### Scenario: No leads

- **GIVEN** an incident nobody wrote a lead in
- **WHEN** the postmortem is written
- **THEN** the document has no leads, and the submission is not refused for
  having none
