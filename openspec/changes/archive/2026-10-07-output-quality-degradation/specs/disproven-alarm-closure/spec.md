## MODIFIED Requirements

### Requirement: A window with no departure disproves an alarm that reported a series

The system SHALL conclude that the alarm was disproven when the retrieved window
holds no departure in any judged signal, the alert states no onset, the alert
reports a series condition, and - where the alert names a rule - the window
carries that rule's series. The conclusion SHALL record which signals were
judged, the paging rule's series among them where it was read, and over what
window, because an assertion that nothing departed is only as good as the span
and the signals it was made over.

#### Scenario: A well service under a series alarm is disproven
- **GIVEN** an alert reporting a high error rate, and a window in which no judged
  signal departs its baseline
- **WHEN** the investigation runs
- **THEN** the alarm is recorded as disproven, naming the signals judged and the
  window judged over

#### Scenario: A departure anywhere in the window is not a disproof
- **GIVEN** an alert reporting a high error rate, and a window in which one
  judged signal departs
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven and the investigation proceeds from the
  onset it measured

#### Scenario: A disproof names the rule's series it judged
- **GIVEN** an alert naming a rule whose series was read, and a window in which
  neither the five signals nor the rule's series departs
- **WHEN** the investigation runs
- **THEN** the alarm is recorded as disproven, and the signals judged include the
  rule's series

## ADDED Requirements

### Requirement: An alarm whose rule's series could not be read is not disproven
The system SHALL NOT conclude that an alarm was disproven when the alert names a
rule and the window carries none of that rule's series. The window was never
shown what the rule watched, so its flatness is no evidence about the alarm; the
investigation SHALL proceed as it does for an alarm a flat window cannot
contradict.

#### Scenario: An unreadable rule leaves the alarm standing
- **GIVEN** an alert naming a rule whose series could not be resolved, and a
  window in which the five signals are flat
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven and the investigation goes on
