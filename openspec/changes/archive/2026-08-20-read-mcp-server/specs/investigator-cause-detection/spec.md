## MODIFIED Requirements

### Requirement: Investigator determines cause_type from the Target Service's current logs
The system SHALL retrieve logs via the `argus-read-mcp` server's
`get_log_lines` tool during investigation and use deterministic keyword
matching against the returned log entries to determine a `cause_type` for at
least the `feature-flag-toggle` scenario.

#### Scenario: Feature-flag-toggle logs are recognized
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `cause_type = "feature-flag-toggle"` at a confidence
  high enough to route to `mitigating`

#### Scenario: No recognizable logs fall back to an undetermined cause
- **GIVEN** the Target Service has no active scenario (`get_log_lines`
  returns an empty list)
- **WHEN** the Investigator investigates the incident
- **THEN** it records a hypothesis with `cause_type` left undetermined
  (`NULL`), at the same confidence the Investigator used before this change
