## MODIFIED Requirements

### Requirement: The verdict is measured from re-queried metrics
After taking an action, the Mitigation agent SHALL re-query the same metrics
channel the Investigator read and SHALL return `confirmed` only where the
service's minutes after the action no longer depart from its baseline. The
judgement of whether a minute departs SHALL be the same one used to locate an
onset, so that the two agents cannot disagree about whether the same minute was
healthy.

Where the minutes after the action are **absent** rather than elevated, this
requirement does not apply and `unreadable-service-recovery` decides. A minute
with no reading has no level to judge, and a window with no departure in it is not
thereby a service that recovered - which is the one case in which reading levels
gives a confident answer to a question nobody asked.

#### Scenario: A recovered service confirms the hypothesis
- **GIVEN** an action has been taken and the minutes after it sit at the
  service's baseline
- **WHEN** the verdict is formed
- **THEN** it is `confirmed`

#### Scenario: A service still failing refutes it
- **GIVEN** an action has been taken and the minutes after it still depart from
  the baseline
- **WHEN** the verdict is formed
- **THEN** it is `refuted`

#### Scenario: The verdict is not read from the minute in progress
- **GIVEN** an action taken partway through a minute
- **WHEN** the verdict is formed
- **THEN** it rests on a minute that began after the action, not on the minute
  the action fell inside

#### Scenario: No recovery within the allowed time is refuted, not an error
- **GIVEN** an action has been taken and the service has not returned to
  baseline within the configured time
- **WHEN** the verdict is formed
- **THEN** it is `refuted`

#### Scenario: Absent minutes are judged by the other rule
- **GIVEN** an action has been taken and no minute at or after it carries a
  reading at all
- **WHEN** the verdict is formed
- **THEN** it is decided by whether the readings return, not by whether anything
  departs
