## ADDED Requirements

### Requirement: Output-quality degradation is a determinable mode

The system SHALL admit `output-quality-degradation` as a failure mode the
Investigator can name: a change made the service's answers worse while every
request still succeeds as fast as before, so the only signal that moved is one
measuring the answers themselves - the series the paging rule watches.

The evidence SHALL be a departure in the paging rule's series with the five fixed
signals flat, and a change at the onset.

#### Scenario: A quality series falling after a deployment is output-quality degradation
- **GIVEN** a window in which the rule's series - the share of purchases
  categorised confidently - falls at the onset, the error rate, latencies and heap
  stay flat, and a revision upgrading the categoriser's model was deployed at the
  onset
- **WHEN** the cause is determined
- **THEN** the mode named is `output-quality-degradation`

### Requirement: Output-quality degradation is separated from a bad deployment

The mode's meaning SHALL separate it from `bad-deployment`, whose new code fails
or slows requests: here every request succeeds at the speed it always did, and
what is wrong is what the answers say.

#### Scenario: The meaning names what moved
- **WHEN** the mode's meaning is read
- **THEN** it says requests still succeed at their usual speed and only a measure
  of the answers moved
