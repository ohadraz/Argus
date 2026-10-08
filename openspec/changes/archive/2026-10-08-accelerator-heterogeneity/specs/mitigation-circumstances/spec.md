## MODIFIED Requirements

### Requirement: A strategy is handed the candidate and the round's circumstances
The system SHALL hand every mitigation strategy two things: the candidate it is
asked about, and one value carrying everything the round established that an
action can be worked out from. That value holds:
- the alerting service;
- the recorded flag changes;
- the stale entry keys the evidence named;
- the recorded deployments;
- the recorded placement, with the onset it was recorded against.

A new kind of input SHALL arrive as part of that value, never as a further
parameter.

#### Scenario: Every per-round input reaches the strategy through one value
- **GIVEN** a round with an alerting service, flag changes, stale entry keys,
  deployments and a recorded placement
- **WHEN** an action is proposed for a candidate
- **THEN** the strategy receives the candidate and a single value holding all
  five

## ADDED Requirements

### Requirement: An unread placement is carried as absent
The system SHALL carry a placement that was not read, or could not be read, as
absent in the circumstances, and never as an empty placement.

#### Scenario: The placement could not be read
- **GIVEN** a round whose placement read went unanswered
- **WHEN** the circumstances are built from a readable flag history
- **THEN** they carry no placement
