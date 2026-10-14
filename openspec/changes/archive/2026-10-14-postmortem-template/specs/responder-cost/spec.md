## MODIFIED Requirements

### Requirement: The response has a cost, computed from minutes and bands
The system SHALL compute what an incident's response cost from the minutes each
responder spent and the pay band of that responder's title. The headline figure
SHALL come from the band's midpoint, and the system SHALL store the minimum
and maximum the same minutes come to at the bottom and top of those bands. The
minimum and maximum SHALL NOT be shown in the postmortem: with the minutes
beside them they give the band away.

#### Scenario: One responder's minutes are priced at their title's band
- **GIVEN** an incident with one responder whose title has a band
- **WHEN** the cost is computed
- **THEN** it is that responder's minutes at the band's midpoint rate, and the
  stored range is the same minutes at the band's minimum and maximum

#### Scenario: Responders on different bands are priced separately
- **GIVEN** an incident with two responders whose titles sit on different levels
- **WHEN** the cost is computed
- **THEN** each is priced at their own band, and the figures are their sums

#### Scenario: An incident nobody engaged with cost nothing
- **GIVEN** an incident no person responded to
- **WHEN** the cost is computed
- **THEN** it is zero, which is a measurement rather than an absence

#### Scenario: The range is not shown
- **GIVEN** a priced response
- **WHEN** the postmortem is shown
- **THEN** the cost appears and its minimum and maximum do not
