## MODIFIED Requirements

### Requirement: Responder timings are read as when people engaged
The system SHALL obtain, for one incident, how many person-minutes the response
took, how many people responded, and the job title each of them held - without
naming any incident-management provider above the port, and without identifying
any responder by name or address. The minutes SHALL already account for how
many people responded, so that nothing above the port multiplies by the count.

#### Scenario: Engagement is answered for an incident
- **WHEN** responder timings are requested for an incident
- **THEN** the answer carries the person-minutes spent, how many responded, and
  the titles they held

#### Scenario: No responder is named above the port
- **WHEN** the postmortem reads responder timings
- **THEN** the answer identifies nobody: it carries titles, a count and a
  duration, and no name, address or provider identifier
