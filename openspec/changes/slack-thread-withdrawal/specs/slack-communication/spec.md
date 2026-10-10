## ADDED Requirements

### Requirement: A withdrawal offer is posted with a button

The system SHALL post an offer to withdraw as a reply in the incident's
thread, naming the person it is made to, saying that confirming stops Argus
and puts back what it changed, and carrying one button that confirms it.

#### Scenario: The withdrawal offer carries a button

- **WHEN** a withdrawal is offered to a person
- **THEN** a reply in the incident's thread names that person, says what
  confirming does, and carries a confirming button

## RENAMED Requirements

- FROM: `### Requirement: An offer is retired once the incident can no longer be resolved`
- TO: `### Requirement: An offer is retired once the incident no longer accepts what it offers`

## MODIFIED Requirements

### Requirement: An offer is retired once the incident no longer accepts what it offers

The system SHALL replace each offer's button, when the incident reaches a
status that no longer accepts what the offer offers, with who ended it and
through which channel, or with the status it ended in. An offer to resolve is
retired at a status that no longer accepts a resolution (`resolved`,
`withdrawn`, `disproven`); one that is `mitigated`, `escalated` or
`recommended` still accepts one, so those offers SHALL keep their button. An
offer to withdraw is retired at every terminal status. A refused update SHALL
be recorded as a communication failure and SHALL NOT change the incident.

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

- **GIVEN** an open offer to resolve
- **WHEN** the incident is mitigated
- **THEN** the offer keeps its button

#### Scenario: A withdrawal offer on a mitigated incident

- **GIVEN** an open offer to withdraw
- **WHEN** the incident is mitigated
- **THEN** the offer says the incident was mitigated, and carries no button

#### Scenario: Withdrawn through the offer

- **GIVEN** an offer to withdraw a person confirmed
- **WHEN** the incident's withdrawal is relayed
- **THEN** the offer says who withdrew it, and carries no button
