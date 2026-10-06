# irregular-flap-scenario Specification

## Purpose
TBD - created by archiving change the-alert-decides-whether-a-mitigation-held. Update Purpose after archive.
## Requirements
### Requirement: A fix that seems to hold while the shop goes on flapping
The Target Service SHALL offer a scenario in which reverting the flag clears the shop for a
minute and the shop then fails single minutes with gaps that do not repeat, often enough
that its rule's condition stays true, until the scenario's real cause is fixed.

#### Scenario: The revert does not resolve the rule
- **GIVEN** the scenario seeded and its flag reverted
- **WHEN** the rule is evaluated through the following minutes
- **THEN** it stays firing

#### Scenario: Argus does not report the revert as mitigated
- **GIVEN** Argus walking the scenario's incident
- **WHEN** the revert is judged
- **THEN** it is refuted, and the incident does not end mitigated

