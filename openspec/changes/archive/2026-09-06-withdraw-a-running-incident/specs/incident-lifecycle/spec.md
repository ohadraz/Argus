## ADDED Requirements

### Requirement: An incident can end because a human took it back

The system SHALL provide `withdrawn` as a terminal status, reachable from every
non-terminal status and from none of the terminal ones. It SHALL be set from
outside the walk rather than derived from the walk's own state, because the fact
it records - that a human took the incident back - is not something the walk can
observe.

#### Scenario: Withdrawal is reachable from anywhere live

- **GIVEN** an incident in any of `acknowledged`, `investigating`, `mitigating`
  or `fixing`
- **WHEN** it is withdrawn
- **THEN** its status becomes `withdrawn` and the transition is recorded on the
  timeline

#### Scenario: Withdrawal is not reachable from a terminal status

- **GIVEN** an incident in `resolved`, `escalated` or `withdrawn`
- **WHEN** it is withdrawn
- **THEN** its status does not change

## MODIFIED Requirements

### Requirement: An incident records when it ended
The system SHALL record the time an incident ended, at the transition that ends
it, whatever ended it - resolved, escalated or withdrawn. How long an incident
lasted is a figure Argus reports, so it SHALL be recorded rather than inferred
from whichever row happened to be written last - an inference that would change
silently the moment anything is logged late, and which for a withdrawn incident
would keep counting while its undo steps were still being written.

#### Scenario: A terminal transition stamps the end
- **WHEN** an incident transitions into a terminal status
- **THEN** the incident records the time of that transition as its end

#### Scenario: A running incident has no end
- **WHEN** an incident has not reached a terminal status
- **THEN** it records no end time

#### Scenario: A withdrawn incident ends when it was withdrawn
- **WHEN** an incident is withdrawn and its actions are then undone
- **THEN** its end is the moment of the withdrawal, not the moment the last undo
  was written
