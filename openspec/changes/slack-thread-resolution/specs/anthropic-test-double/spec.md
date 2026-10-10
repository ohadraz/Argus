## ADDED Requirements

### Requirement: The double holds a call when a test says so

The double SHALL, after `POST /double-control/hold`, keep a call that arrives
with nothing queued waiting, rather than refusing it, until the next seed
answers it or `POST /double-control/release` refuses it. A seed SHALL end the
hold, so a later call with nothing queued is refused rather than held with
nothing coming. Without a hold, a call with nothing queued SHALL be refused at
once. `reset` SHALL end a hold, refusing a call held.

#### Scenario: A held call is answered by the next seed

- **GIVEN** a double told to hold, with nothing queued
- **WHEN** a call arrives, and a response is then seeded
- **THEN** the call waits, and is answered with the seeded response

#### Scenario: A released call is refused

- **GIVEN** a call waiting on a hold
- **WHEN** the test releases it
- **THEN** the call is refused, as a call with nothing queued is

#### Scenario: No hold

- **GIVEN** a double with nothing queued and no hold
- **WHEN** a call arrives
- **THEN** it is refused at once
