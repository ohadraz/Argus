# incident-postmortem

## Purpose

Covers what the Postmortem agent produces on a terminal transition: which
figures are measured, which are estimated and disclosed as such, that the
model supplies prose and never a number, and that the agent terminates even
when the document is incomplete.

## Requirements

### Requirement: A postmortem is written once, when the incident ends
The system SHALL write exactly one postmortem for an incident, on the
transition that ends it, whether it ended resolved or escalated. An incident
that ends without a cause SHALL still get a postmortem, because what was ruled
out is what the next responder needs.

#### Scenario: A resolved incident is written up
- **WHEN** an incident reaches its terminal transition having identified a
  cause
- **THEN** one postmortem row is written for that incident

#### Scenario: An escalated incident is written up
- **WHEN** an incident reaches its terminal transition without identifying a
  cause
- **THEN** one postmortem row is written, recording that no cause was
  identified rather than omitting the document

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

### Requirement: The loss estimate is measured revenue, not a modelled one
The system SHALL estimate customer loss as the revenue a calm period before the
incident predicts for a window of the incident's length, less the revenue
actually taken during the incident. Both terms SHALL be revenue the payment
provider reported over a window. No term of the estimate SHALL be supplied by
the model, and the estimate SHALL be stored alongside the assumptions it rests
on.

The incident SHALL be dated from its onset rather than from the alert that
announced it, so that minutes in which the service was already failing do not
enter the calm baseline. An incident with no recorded onset SHALL leave the
estimate absent with that reason recorded, rather than dated from the alert.

The estimate SHALL NOT be negative: a window in which more was taken than the
calm period predicted SHALL be reported as no measurable loss.

The estimate SHALL name the currency it is stated in. Where takings in another
currency were converted to reach it, the rate used and the date that rate was
fixed SHALL be recorded among the assumptions, and takings in a currency no
rate covered SHALL be excluded with that exclusion recorded - never converted
at a rate nothing published.

#### Scenario: A shop that took less than its calm period predicted has lost the difference
- **GIVEN** an incident during which the shop took less than the period before
  its onset predicts for a window of that length
- **WHEN** the estimate is computed
- **THEN** the estimate is the difference between the two

#### Scenario: A shop that took more lost nothing measurable
- **GIVEN** an incident during which the shop took more than the calm period
  predicted
- **WHEN** the estimate is computed
- **THEN** the estimate is zero rather than a negative amount

#### Scenario: An incident with no recorded onset is not dated from its alert
- **GIVEN** an incident for which no onset was recorded
- **WHEN** the estimate would be computed
- **THEN** no estimate is published, and the absence of an onset is recorded as
  the reason

#### Scenario: The assumptions are stored with the figure
- **WHEN** a loss estimate is stored
- **THEN** the assumptions it rests on are stored with it, naming at least the
  windows compared

#### Scenario: A converted figure discloses the rate it rests on
- **GIVEN** an incident during which the service was paid in a currency other
  than the one reported in
- **WHEN** the estimate is stored
- **THEN** the assumptions name the rate used and the date it was fixed

#### Scenario: A currency no rate covers is excluded rather than guessed at
- **GIVEN** takings in a currency the rate source publishes nothing for
- **WHEN** the estimate is computed
- **THEN** those takings are left out of it and the exclusion is recorded with
  the figure

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

### Requirement: Published prose may not name a figure the system did not compute
The system SHALL check the executive summary for stated currency amounts, and
SHALL treat an amount that is not the computed estimate as a fault in the
answer, asking once more for a corrected one. Where no estimate could be
computed, any stated amount SHALL be a fault. The summary is published as
written, so an invented figure would otherwise reach the reader least able to
check it.

#### Scenario: A summary naming an invented amount is challenged
- **GIVEN** an answer whose executive summary states an amount that is not the
  computed estimate
- **WHEN** the document is assembled
- **THEN** the model is asked once more, and the invented amount is named as
  the reason

#### Scenario: A summary agreeing with the computed figure is accepted
- **WHEN** the summary states the computed estimate
- **THEN** it is accepted without a further call

### Requirement: The metrics window covers the whole incident
The system SHALL read metrics for a window spanning the incident's own start
and end, rather than reusing what the investigation happened to read. The
investigation stops reading once it has a cause, so the recovery between the
mitigation and the end of the incident is not in what it stored.

#### Scenario: The window reaches the end of the incident
- **WHEN** the postmortem reads metrics
- **THEN** the window it requests ends no earlier than the incident's end

### Requirement: The document is checked once and then handed off regardless
The system SHALL check its own document for missing required fields, and where
any are missing SHALL ask the model once more, naming them. Whatever comes back
SHALL be written, with the document recording whether it is complete. There
SHALL be no further attempt.

#### Scenario: A complete document is written without a second call
- **WHEN** the first answer carries every required field
- **THEN** the document is written and marked complete, with no second model
  call

#### Scenario: A second incomplete answer is still written
- **GIVEN** a first answer missing required fields
- **WHEN** the second answer is also missing fields
- **THEN** the document is written with what is present and marked incomplete
