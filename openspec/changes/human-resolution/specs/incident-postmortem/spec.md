## MODIFIED Requirements

### Requirement: A postmortem is written once, when the incident ends
The system SHALL write exactly one postmortem for an incident: on the transition
that ends it, for every ending the walk derives (mitigated, recommended,
escalated or disproven), and for a resolution a person reported while the walk
was still running or before it began. An incident that ends without a cause
SHALL still get a postmortem, because what was ruled out is what the next
responder needs. An incident whose alarm was disproven SHALL get one too: there,
what was ruled out is the alarm itself.

A resolution reported after the postmortem was written SHALL NOT produce a
second one.

A withdrawn incident is the exception and the only one. The walk does not
derive that ending. It leaves the graph at the next node boundary instead of
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

#### Scenario: An incident a person resolved mid-walk is written up
- **WHEN** a person resolves an incident while its walk is running
- **THEN** one postmortem row is written for that incident

#### Scenario: A resolution after the write-up writes nothing more
- **GIVEN** an incident whose postmortem is written
- **WHEN** a person resolves it
- **THEN** no second postmortem row is written
