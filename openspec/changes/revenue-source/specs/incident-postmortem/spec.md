## MODIFIED Requirements

### Requirement: The loss estimate is a revenue rate scaled by what the incident touched
The system SHALL estimate customer loss as the service's baseline revenue rate
over the incident's duration, scaled by the fraction of traffic that failed and
by how much of the affected path carried revenue. The estimate SHALL be stored
alongside the assumptions it rests on, and SHALL never be presented as a
measurement.

The estimate SHALL name the currency it is stated in. Where takings in another
currency were converted to reach it, the rate used and the date that rate was
fixed SHALL be recorded among the assumptions, and takings in a currency no
rate covered SHALL be excluded with that exclusion recorded - never converted
at a rate nothing published.

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
