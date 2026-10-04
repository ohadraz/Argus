## MODIFIED Requirements

### Requirement: A postmortem is written once, when the incident ends
The system SHALL write exactly one postmortem for an incident, on the
transition that ends it, for every ending the walk derives - resolved,
mitigated, recommended, escalated or disproven. An incident that ends without a
cause SHALL still get a postmortem, because what was ruled out is what the next
responder needs - and an incident whose alarm was disproven SHALL get one too,
where what was ruled out is the alarm itself.

A withdrawn incident is the exception and the only one: it is the ending the walk
does not derive, the walk leaves the graph at the next node boundary rather than
routing onwards, and the person who took the incident back is not waiting to be
told what Argus made of it.

#### Scenario: A resolved incident is written up
- **WHEN** an incident reaches its terminal transition having identified a
  cause
- **THEN** one postmortem row is written for that incident

#### Scenario: An escalated incident is written up
- **WHEN** an incident reaches its terminal transition without identifying a
  cause
- **THEN** one postmortem row is written, recording that no cause was
  identified rather than omitting the document

#### Scenario: A disproven incident is written up
- **WHEN** an incident reaches its terminal transition with its alarm disproven
- **THEN** one postmortem row is written, recording the condition the rule
  reported, what the judged signals held instead, and that the rule rather than
  the service is what to look at

## ADDED Requirements

### Requirement: A disproven incident's document reports no impact rather than an absent one

The system SHALL report every computed figure on a disproven incident's
postmortem as the measurement it is, and SHALL NOT leave a figure absent on the
ground that nothing happened. A window with no departure has a loss estimate of
zero because it was measured at zero, and a document that omitted it would read
as one whose source was unavailable.

#### Scenario: A measured zero is stated as zero
- **WHEN** a postmortem is written for a disproven incident
- **THEN** its loss estimate is the figure computed from a window with no
  departure, and is not omitted
