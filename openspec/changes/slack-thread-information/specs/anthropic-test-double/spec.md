## MODIFIED Requirements

### Requirement: The double holds a call when a test says so

The double SHALL, after `POST /double-control/hold`, keep the next call to
arrive waiting until `POST /double-control/release`, whatever is queued and
whether or not it is recording. A seed SHALL NOT end a hold. On release the
held call SHALL be answered as a call arriving then would be: by the next
seed, or upstream while recording, or refused. Calls other than the held one
SHALL be answered as without a hold. A release before any call has arrived
SHALL end the hold, so the next call is answered as without one. `reset` SHALL
end a hold, refusing a call held.

#### Scenario: A held call takes the next seed on release

- **GIVEN** a double with responses queued, told to hold
- **WHEN** a call arrives, a response is seeded, and the test releases
- **THEN** the call waits through the seed, and is answered on release with
  the response at the head of the queue

#### Scenario: A hold is honoured while recording

- **GIVEN** a double recording, told to hold
- **WHEN** a call arrives, and the test releases
- **THEN** the call waits, and goes upstream on release

#### Scenario: A released call with nothing queued is refused

- **GIVEN** a call waiting on a hold, with nothing queued and no recording
- **WHEN** the test releases it
- **THEN** the call is refused, as a call with nothing queued is

#### Scenario: A hold released before any call arrives

- **GIVEN** a double told to hold, with a response queued
- **WHEN** the test releases, and then a call arrives
- **THEN** the call is answered at once with the queued response

#### Scenario: No hold

- **GIVEN** a double with nothing queued and no hold
- **WHEN** a call arrives
- **THEN** it is refused at once
