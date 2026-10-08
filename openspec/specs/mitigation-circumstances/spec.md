# mitigation-circumstances Specification

## Purpose
What a mitigation strategy is handed: the candidate it answers, and one value
carrying everything the round established that an action can be worked out
from - built in one place, and not at all where the flag history could not be
read.
## Requirements
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

### Requirement: An unreadable flag history yields no circumstances
The system SHALL build the round's circumstances in one place, and SHALL build
none where the flag history could not be read, so that nothing is proposed for
any candidate. An alert that mentions no cache and a platform history that was
not read SHALL each be carried as empty.

#### Scenario: The flag provider could not be read
- **GIVEN** a round whose flag history is unreadable
- **WHEN** the circumstances are built
- **THEN** there are none, and no candidate is answered by an action

#### Scenario: Absent keys and an unread platform history are empty
- **GIVEN** an alert naming no stale entry keys and a platform history that was
  not read
- **WHEN** the circumstances are built from a readable flag history
- **THEN** they carry no keys and no deployments

### Requirement: An unread placement is carried as absent
The system SHALL carry a placement that was not read, or could not be read, as
absent in the circumstances, and never as an empty placement.

#### Scenario: The placement could not be read
- **GIVEN** a round whose placement read went unanswered
- **WHEN** the circumstances are built from a readable flag history
- **THEN** they carry no placement

