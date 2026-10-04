## ADDED Requirements

### Requirement: `disproven` is the ending of an alarm the metrics contradicted

The system SHALL end an incident as `disproven` where the investigation
established that the alarm's own claim was not in the window it read, and SHALL
reach that ending from `investigating` without passing through `mitigating`.

It is a fourth ending beside `mitigated`, `escalated` and `recommended`, and it
is the only one that reports the absence of an incident. The transition SHALL be
published as every other transition is, so that a dashboard and a timeline
account for it without a special case.

#### Scenario: A disproven alarm goes straight from investigating to disproven
- **GIVEN** an incident whose alert reported a series condition and whose window
  held no departure
- **WHEN** the walk runs to its end
- **THEN** the incident's statuses are `investigating` then `disproven`, and it
  never entered `mitigating`

#### Scenario: The transition is published
- **WHEN** an incident enters `disproven`
- **THEN** an event is published for that transition, as for every other

### Requirement: A disproven alarm records what was judged and over what span

The system SHALL record, on an incident that ended `disproven`, which signals
were judged and over what window - so that a responder can tell a disproof from
a claim, and so that one made over too narrow a window can be recognised later
as the mistake it was.

#### Scenario: The record carries the span and the signals
- **WHEN** an incident ends `disproven`
- **THEN** its timeline records the signals judged and the window judged over
