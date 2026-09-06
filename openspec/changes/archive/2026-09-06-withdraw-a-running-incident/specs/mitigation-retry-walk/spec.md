## ADDED Requirements

### Requirement: A withdrawal ends the walk

Where an incident is withdrawn mid-walk, the system SHALL stop the walk without
trying any remaining candidate and without opening a further investigation
round. The walk SHALL NOT treat the withdrawal as a refutation: nothing was
measured, so no candidate is marked tested and no verdict is recorded for the
attempt in progress.

#### Scenario: Candidates left are not tried

- **GIVEN** an incident mid-walk with two untried candidates above the mitigate
  threshold
- **WHEN** it is withdrawn
- **THEN** no action is proposed or taken for either, and the walk ends

#### Scenario: The attempt in progress is not scored

- **GIVEN** an incident withdrawn while an action's verification window is open
- **WHEN** the walk ends
- **THEN** the candidate is not marked tested and no verdict is recorded for it

#### Scenario: No further round is opened

- **GIVEN** an incident withdrawn with investigation rounds remaining
- **WHEN** the walk ends
- **THEN** no further investigation is started
