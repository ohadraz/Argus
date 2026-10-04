## MODIFIED Requirements

### Requirement: An onset stated by the alert is accepted when none can be measured

The system SHALL use the onset an alert states whenever no onset can be measured
from the retrieved window, and SHALL investigate from it exactly as it would from
a measured one.

This is what lets an incident be found by something other than a health series. A
window that is flat because nothing was ever wrong and a window that is flat
because what is wrong is a value are the same window, and only the alert can tell
them apart.

An alert that states no onset is not one case. One reports a condition on a
series the system also retrieves, and a window with no departure in it disproves
that alert. One reports a finding of its own, which no series carries, and a flat
window is no evidence against it - so that investigation proceeds with no onset
rather than ending.

#### Scenario: A flat window with a stated onset is investigated
- **GIVEN** an alert carrying an onset, for a window in which no series departs
- **WHEN** the investigation runs
- **THEN** it proceeds from the stated onset, and a model is asked

#### Scenario: A flat window under a series alarm with no stated onset is disproven
- **GIVEN** an alert reporting a series condition and carrying no onset, for a
  window in which no series departs
- **WHEN** the investigation runs
- **THEN** it returns without asking a model, and reports that the alarm was
  disproven

#### Scenario: A flat window under a finding with no stated onset is investigated
- **GIVEN** an alert reporting a finding of its own and carrying no onset, for a
  window in which no series departs
- **WHEN** the investigation runs
- **THEN** a model is asked, and the investigation works without an onset
