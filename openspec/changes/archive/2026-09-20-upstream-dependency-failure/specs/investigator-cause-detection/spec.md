## ADDED Requirements

### Requirement: An upstream dependency failure is a determinable failure mode
The system SHALL carry `upstream-dependency-failure` in the closed set of
failure modes, and the Investigator SHALL be able to determine it from the
evidence it retrieves: failures that name a third party, latency that moved
with the errors, and no change of Argus's own to account for either.

A determination of this mode SHALL be recorded at a confidence read the same
way every other mode's is. It SHALL NOT be treated as an undetermined cause -
the mode is known, and what follows from it is a decision rather than a gap.

#### Scenario: Upstream failures are recognised
- **GIVEN** the Target Service's active scenario is `upstream-dependency-failure`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `failure_mode = "upstream-dependency-failure"` and
  records the evidence it relied on

#### Scenario: A determined upstream cause is not an undetermined one
- **GIVEN** the Investigator determined `upstream-dependency-failure`
- **WHEN** the hypothesis is recorded
- **THEN** `failure_mode` is that value rather than `NULL`, and the incident is
  not recorded as a cause nobody could determine
