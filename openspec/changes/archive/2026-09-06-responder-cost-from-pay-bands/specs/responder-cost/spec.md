## ADDED Requirements

### Requirement: The response has a cost, computed from minutes and bands
The system SHALL compute what an incident's response cost from the minutes each
responder spent and the pay band of that responder's title. The headline figure
SHALL come from the band's midpoint, and the system SHALL report the minimum
and maximum the same minutes come to at the bottom and top of those bands.

#### Scenario: One responder's minutes are priced at their title's band
- **GIVEN** an incident with one responder whose title has a band
- **WHEN** the cost is computed
- **THEN** it is that responder's minutes at the band's midpoint rate, and the
  range is the same minutes at the band's minimum and maximum

#### Scenario: Responders on different bands are priced separately
- **GIVEN** an incident with two responders whose titles sit on different levels
- **WHEN** the cost is computed
- **THEN** each is priced at their own band, and the figures are their sums

#### Scenario: An incident nobody engaged with cost nothing
- **GIVEN** an incident no person responded to
- **WHEN** the cost is computed
- **THEN** it is zero, which is a measurement rather than an absence

### Requirement: An unpriced title leaves the whole figure absent
The system SHALL report no responder cost for an incident where any responder's
title has no band, and SHALL say which title. A figure covering the responders
who happened to match SHALL NOT be reported: a cost missing a person is not a
smaller cost, it is a wrong one.

#### Scenario: One unpriced title suppresses the figure
- **GIVEN** an incident with two responders, one of whose titles has no band
- **WHEN** the cost is computed
- **THEN** no figure is reported, and what is written down names that title

#### Scenario: An unreadable source is distinguishable from nobody responding
- **GIVEN** one incident nobody responded to and one whose HR source could not
  be read
- **WHEN** both are reported
- **THEN** the first reports zero and the second reports no figure, each saying
  which it is

### Requirement: An annual band becomes a per-minute rate through a stated year
The system SHALL convert an annual band into a rate per minute using a
configured number of working hours in a year, and SHALL state that number with
the figure. A figure derived from a divisor is reproducible only where the
divisor is recorded.

#### Scenario: The working year is stated on the document
- **GIVEN** a computed responder cost
- **WHEN** it is reported
- **THEN** the assumptions state the working hours a year it was derived with

#### Scenario: A different working year gives a different rate
- **GIVEN** two deployments configured with different working years
- **WHEN** the same minutes at the same band are priced
- **THEN** the figures differ, each stating its own divisor
