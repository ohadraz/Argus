# exchange-rate-source

## Purpose

Covers the rate a converted figure rests on: where it comes from, how long it
is held, what happens when the provider cannot be reached, and that the date it
was fixed travels with every figure converted at it.

## Requirements

### Requirement: A converted figure rests on a published rate, never on a judgment
The system SHALL convert between currencies only at a rate obtained from a rate
provider that publishes them. No rate SHALL be supplied by the model, inferred
from a figure, or defaulted to.

#### Scenario: No rate means no converted figure
- **GIVEN** a currency for which no rate can be obtained
- **WHEN** a figure in that currency is to be converted
- **THEN** it is not converted, and its exclusion is recorded

#### Scenario: The model is never asked for a rate
- **WHEN** a document containing converted figures is produced
- **THEN** the rate used came from the rate source, and nothing in the model's
  answer was read as a rate

### Requirement: A rate is fetched once for the day it was fixed
The system SHALL obtain rates for a given day at most once and reuse them for
the rest of that day. Reference rates are fixed once per business day, so a
second fetch within a day answers with what is already held.

#### Scenario: A second read the same day makes no second request
- **GIVEN** rates already obtained for today
- **WHEN** a further conversion is needed the same day
- **THEN** the held rates are used and the provider is not called again

### Requirement: A rate that could not be refreshed is used only with its date said
The system SHALL, when the rate provider cannot be reached, use the most recent
rates it holds, and SHALL record the date those rates were fixed wherever a
converted figure appears. When it holds none, the figure SHALL be absent with
that reason rather than converted.

#### Scenario: Yesterday's rate is used and disclosed
- **GIVEN** the rate provider cannot be reached and rates from an earlier day
  are held
- **WHEN** a figure is converted
- **THEN** the earlier rates are used and the date they were fixed is recorded
  with the figure

#### Scenario: No rate held and none obtainable leaves the figure absent
- **GIVEN** the rate provider cannot be reached and no rates are held
- **WHEN** a figure would be converted
- **THEN** no figure is published and the reason is recorded

### Requirement: The currency a figure is stated in is configured, not guessed
The system SHALL take the currency it reports in from configuration, and SHALL
name that currency wherever a converted figure is published.

#### Scenario: A published figure names its currency
- **WHEN** a converted figure is stored
- **THEN** the currency it is stated in is stored with it
