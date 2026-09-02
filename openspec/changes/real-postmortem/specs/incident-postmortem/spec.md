## ADDED Requirements

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
`customer_loss_estimate_usd` from recorded data and SHALL store those computed
values. A number appearing in the model's prose SHALL never be parsed back out
and stored, even when the two disagree.

#### Scenario: Prose disagreeing with the computation does not change it
- **GIVEN** a computed loss estimate
- **WHEN** the model's summary states a different figure
- **THEN** the stored estimate is the computed one

#### Scenario: Tokens are counted from the replay log
- **WHEN** a postmortem is written for an incident
- **THEN** `tokens_spent` is the sum of the token usage reported by that
  incident's own recorded model calls

### Requirement: The loss estimate is a revenue rate scaled by what the incident touched
The system SHALL estimate customer loss as the service's baseline revenue rate
over the incident's duration, scaled by the fraction of traffic that failed and
by how much of the affected path carried revenue. The estimate SHALL be stored
alongside the assumptions it rests on, and SHALL never be presented as a
measurement.

#### Scenario: An incident away from the revenue path estimates no loss
- **GIVEN** an incident whose failures were confined to a path carrying no
  revenue
- **WHEN** the estimate is computed
- **THEN** the estimate is zero, and the assumption that the path carried no
  revenue is recorded with it

#### Scenario: The assumptions are stored with the figure
- **WHEN** a loss estimate is stored
- **THEN** the assumptions it rests on are stored with it, naming at least how
  much of the affected path was taken to carry revenue

### Requirement: A judgment comes from the model, a measurement never does
The system SHALL ask the model for how much of the affected path carried
revenue, and SHALL treat that answer as a disclosed judgment rather than a
measurement. Every other term of the estimate SHALL be read from recorded data.

#### Scenario: The model supplies the weight and nothing else numeric
- **WHEN** the model answers
- **THEN** the only number taken from its answer is how much of the affected
  path carried revenue

### Requirement: An unavailable source leaves its figure absent, never zero
The system SHALL leave a figure absent when the data it needs could not be
read, and SHALL record why in the document's assumptions. An unreadable source
SHALL NOT be reported as a measured zero.

#### Scenario: No responder data means no engineer minutes
- **GIVEN** no source can say when a person engaged
- **WHEN** the postmortem is written
- **THEN** `engineer_minutes` is absent, and the assumptions say why

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
