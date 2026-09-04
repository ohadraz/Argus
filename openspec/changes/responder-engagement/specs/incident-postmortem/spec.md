## MODIFIED Requirements

### Requirement: Every reported figure is computed, never taken from the model
The system SHALL compute `engineer_minutes`, `tokens_spent` and
`customer_loss_estimate` from recorded data and SHALL store those computed
values. A number appearing in the model's prose SHALL never be parsed back out
and stored, even when the two disagree.

`engineer_minutes` SHALL be person-minutes as the on-call source reports them -
each responder's own acknowledgement to the end of the incident, summed -
rather than the incident's own length. An incident's length charges to a person
the time it spent waiting for one, and charges to one person the time two of
them spent.

#### Scenario: Prose disagreeing with the computation does not change it
- **GIVEN** a computed loss estimate
- **WHEN** the model's summary states a different figure
- **THEN** the stored estimate is the computed one

#### Scenario: Tokens are counted from the replay log
- **WHEN** a postmortem is written for an incident
- **THEN** `tokens_spent` is the sum of the token usage reported by that
  incident's own recorded model calls

#### Scenario: The minutes are person-minutes from each acknowledgement
- **GIVEN** an incident two people acknowledged, some time after it began
- **WHEN** the postmortem is written
- **THEN** `engineer_minutes` is both of their spans added together, and not
  the incident's whole length

### Requirement: An unavailable source leaves its figure absent, never zero
The system SHALL leave a figure absent when the data it needs could not be
read, and SHALL record why in the document's assumptions. An unreadable source
SHALL NOT be reported as a measured zero. An incident that nobody attended,
answered as such by a source that could be read, SHALL be reported as no
engagement rather than as an absence.

#### Scenario: No responder data means no engineer minutes
- **GIVEN** no source can say when a person engaged
- **WHEN** the postmortem is written
- **THEN** `engineer_minutes` is absent, and the assumptions say why

#### Scenario: An unattended incident reports no engagement rather than nothing
- **GIVEN** an on-call source that answers that nobody acknowledged the
  incident
- **WHEN** the postmortem is written
- **THEN** `engineer_minutes` is zero, and it is not recorded as an unreadable
  source

#### Scenario: An unreachable revenue source is not zero revenue
- **GIVEN** the revenue source cannot be read
- **WHEN** the postmortem is written
- **THEN** the loss estimate is absent rather than zero
