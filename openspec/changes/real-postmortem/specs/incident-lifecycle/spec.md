## ADDED Requirements

### Requirement: An incident records when it ended
The system SHALL record the time an incident ended, at the transition that ends
it, whether it ended resolved or escalated. How long an incident lasted is a
figure Argus reports, so it SHALL be recorded rather than inferred from
whichever row happened to be written last - an inference that would change
silently the moment anything is logged late.

#### Scenario: A terminal transition stamps the end
- **WHEN** an incident transitions into a terminal status
- **THEN** the incident records the time of that transition as its end

#### Scenario: A running incident has no end
- **WHEN** an incident has not reached a terminal status
- **THEN** it records no end time
