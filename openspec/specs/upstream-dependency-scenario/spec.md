# upstream-dependency-scenario Specification

## Purpose
TBD - created by archiving change upstream-dependency-failure. Update Purpose after archive.
## Requirements
### Requirement: The shop depends on a payment provider it does not own
The Target Service SHALL render the account page partly from a third-party
payment provider - the shopper's stored card - so that the provider sits on the
request path in source rather than in a fixture. The call SHALL be made through
a seam the generator can answer without a network round trip, because the
window's metrics are produced by rendering the page many times a minute.

The shop SHALL NOT retry, fall back, or degrade when the provider fails. The
failure SHALL reach the request boundary and be recorded there the way every
other failure is, with the provider named and the raising line reported.

#### Scenario: A healthy provider leaves the page as it was
- **GIVEN** the payment provider is answering
- **WHEN** an account page is rendered
- **THEN** the page renders successfully and the shop's error rate is its
  baseline

#### Scenario: A failing provider fails the page, and says whose fault it is
- **GIVEN** the payment provider is refusing requests
- **WHEN** an account page is rendered
- **THEN** the render fails, and the recorded failure names the provider's host
  and the HTTP status it answered with

### Requirement: The scenario's signature is errors and latency with nothing changed
Seeding `upstream-dependency-failure` SHALL make the provider fail from the
scenario's onset. While it is failing, the generated telemetry SHALL report a
raised error rate **and** raised latency - requests wait on the provider before
failing - while memory stays at its baseline, no flag moves, and the deploy
history records no change.

#### Scenario: Both signals move
- **GIVEN** the `upstream-dependency-failure` scenario has been seeded
- **WHEN** the metrics window is read
- **THEN** minutes from the onset report an error rate and a p95 above their
  baselines, and memory at its baseline

#### Scenario: Nothing internal accounts for it
- **GIVEN** the `upstream-dependency-failure` scenario has been seeded
- **WHEN** the change events and flag history for the window are read
- **THEN** neither reports a change

#### Scenario: The logs name the third party
- **GIVEN** the `upstream-dependency-failure` scenario has been seeded
- **WHEN** the log lines for the window are read
- **THEN** failure lines name the provider's host and the status it returned

### Requirement: No Argus action ends the scenario
The scenario's condition SHALL be the provider's state, which no mitigation in
Argus's closed set can change. Reverting a flag, restarting the service or
rolling back a deploy SHALL leave the telemetry failing exactly as it was, and
the condition SHALL clear only when the scenario is reset through the Target
Service's own control.

#### Scenario: A restart changes nothing
- **GIVEN** the scenario is active
- **WHEN** the service is restarted
- **THEN** the next minutes report the same failing telemetry

#### Scenario: A reset ends it
- **GIVEN** the scenario is active
- **WHEN** the scenario is reset through scenario control
- **THEN** no scenario is active and the service serves no telemetry, as it
  does with nothing staged

