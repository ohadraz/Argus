## ADDED Requirements

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
