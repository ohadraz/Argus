## MODIFIED Requirements

### Requirement: Every reported figure is computed, never taken from the model
The system SHALL compute `engineer_minutes`, `tokens_spent`,
`responder_cost_estimate` and `customer_loss_estimate` from recorded data and
SHALL store those computed values. A number appearing in the model's prose
SHALL never be parsed back out and stored, even when the two disagree.

`engineer_minutes` SHALL be person-minutes as the on-call source reports them -
each responder's own acknowledgement to the end of the incident, summed -
rather than the incident's own length. An incident's length charges to a person
the time it spent waiting for one, and charges to one person the time two of
them spent.

`responder_cost_estimate` SHALL be those same minutes priced at the pay band of
each responder's title, from the band's midpoint, and SHALL be accompanied by
what the same minutes come to at the bottom and top of those bands. A band is a
range, and a midpoint published alone claims a precision the source does not
have.

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

#### Scenario: The response cost is priced from those same minutes
- **GIVEN** an incident whose responders' titles all have bands
- **WHEN** the postmortem is written
- **THEN** `responder_cost_estimate` prices exactly the minutes
  `engineer_minutes` reports, and the document carries its range beside it

#### Scenario: An unpriced title leaves the cost absent and the minutes present
- **GIVEN** an incident one of whose responders holds a title with no band
- **WHEN** the postmortem is written
- **THEN** `engineer_minutes` is still reported, `responder_cost_estimate` is
  absent, and the assumptions name the title that could not be priced
