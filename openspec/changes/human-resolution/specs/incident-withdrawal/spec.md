## MODIFIED Requirements

### Requirement: A live incident can be withdrawn

The system SHALL allow a live incident to be withdrawn, meaning a human has
taken it back and Argus is to stop working on it. Withdrawal SHALL be accepted
for any non-terminal incident and SHALL be refused for a terminal one, so that
withdrawal cannot undo a mitigation that is confirmed and holding the service
up. Withdrawing an already-withdrawn incident SHALL be accepted and change
nothing further.

The withdrawal SHALL record who withdrew the incident and the channel it came
through. From the Argus UI that is "demo user".

#### Scenario: A running incident is withdrawn

- **GIVEN** an incident that has not reached a terminal status
- **WHEN** it is withdrawn from the Argus UI
- **THEN** its status becomes `withdrawn`, and its timeline records that "demo
  user" withdrew it from the Argus UI

#### Scenario: A finished incident cannot be withdrawn

- **GIVEN** an incident that has reached a terminal status
- **WHEN** it is withdrawn
- **THEN** the request is refused, the status is unchanged, and nothing Argus
  did is undone

#### Scenario: Withdrawing twice does nothing twice

- **GIVEN** an incident already withdrawn
- **WHEN** it is withdrawn again
- **THEN** the request is accepted, and no action is undone a second time
