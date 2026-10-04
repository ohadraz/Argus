## ADDED Requirements

### Requirement: The recovery wait allows for the metrics source's reporting lag
The system SHALL extend the deadline by which an action's recovery must have
shown by `metrics_reporting_lag_minutes` (default 1), so that a metrics source
which reports a minute only once it has ended is not read as showing no
recovery before the minutes that would carry it can have been reported.

#### Scenario: A lagging source does not refute a recovery
- **GIVEN** a reporting lag of 1 and a source that reports each minute only
  after it ends
- **WHEN** an action ends the incident and the following minutes are clear
- **THEN** the wait lasts until those minutes are reported, and the action is
  confirmed rather than refuted

#### Scenario: A lag of 0 leaves the deadline where it was
- **GIVEN** a reporting lag of 0
- **WHEN** the recovery deadline is worked out for an action
- **THEN** it is the same instant it would be with no lag allowed for
