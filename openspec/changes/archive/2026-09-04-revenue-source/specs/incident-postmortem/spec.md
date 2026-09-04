## RENAMED Requirements

- FROM: `### Requirement: The loss estimate is a revenue rate scaled by what the incident touched`
- TO: `### Requirement: The loss estimate is measured revenue, not a modelled one`

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: A judgment comes from the model, a measurement never does
