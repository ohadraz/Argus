## MODIFIED Requirements

### Requirement: Past incidents remain readable

The view SHALL offer a history of incidents and their outcomes, and the postmortem where one exists, reached through the view's navigation rather than as its front page - what is happening now is what somebody opening Argus during an incident came for. A demo that can only show the incident currently running cannot show what the system has learned.

#### Scenario: Opening a past incident

- **WHEN** an incident from an earlier run is opened from the history
- **THEN** its walk and its postmortem render the same way a current incident's do

#### Scenario: An incident with no postmortem

- **WHEN** an incident that has no postmortem is shown
- **THEN** the page says there is none, and does not fail

#### Scenario: Reaching the history

- **WHEN** a reader opens Argus and wants an earlier incident
- **THEN** the history is reachable through the view's navigation, without knowing a URL
