## ADDED Requirements

### Requirement: The paging rule's series is one of the signals an onset is found in
Where a window carries a rule reading, the onset, departure and recovery SHALL be found in it
as in the five fixed judged signals, in the direction its rule calls worse. A window that
carries none SHALL be judged on the five alone, exactly as before.

#### Scenario: An onset only the rule's series shows
- **GIVEN** a window whose five fixed signals never depart and whose rule reading departs and
  persists
- **WHEN** the onset is found
- **THEN** it is the first minute of the rule reading's departure

#### Scenario: Recovery waits for the rule's series too
- **GIVEN** a window whose rule reading departed and has since come back
- **WHEN** the recovery is found
- **THEN** it is the minute the rule reading came back, as for any judged signal
