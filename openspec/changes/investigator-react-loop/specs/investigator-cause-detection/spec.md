## MODIFIED Requirements

### Requirement: Investigator determines cause_type from the Target Service's current logs
The system SHALL retrieve logs via the `argus-read-mcp` server's
`get_log_lines` tool during investigation, windowed and anchored on the metric
onset, and SHALL determine a `cause_type` by asking a real LLM to judge the
retrieved evidence. Deterministic keyword matching SHALL NOT be the mechanism.
An undetermined cause SHALL be reported at a confidence below the mitigate
threshold.

#### Scenario: Feature-flag-toggle logs are recognized
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `cause_type = "feature-flag-toggle"` at a confidence
  high enough to route to `mitigating`

#### Scenario: No recognizable logs report an undetermined cause, not a confident one
- **GIVEN** the Target Service has no active scenario (`get_log_lines`
  returns an empty list)
- **WHEN** the Investigator investigates the incident
- **THEN** it records a hypothesis with `cause_type` left undetermined
  (`NULL`), at a confidence below the mitigate threshold, and the incident
  routes to `escalated` rather than to `mitigating`

## ADDED Requirements

### Requirement: The evidence behind a cause determination is recorded
The system SHALL record which retrieved log lines the verdict relied on, so a
human picking up the incident can tell what the determination was based on and
distinguish a well-evidenced call from a thin one.

#### Scenario: Supporting evidence accompanies a determined cause
- **GIVEN** the Investigator determines a cause for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the log lines the verdict relied on are recorded with it
