## MODIFIED Requirements

### Requirement: Investigator determines cause_type from the Target Service's current logs
The system SHALL make the `argus-read-mcp` server's `get_log_lines` and
`get_change_events` tools available to the model during investigation, and SHALL
dispatch them when the model calls them. It SHALL determine a `cause_type`
by asking a real LLM to judge the evidence it retrieved - metrics, logs and
changes, whichever of them it chose to read. Deterministic keyword matching SHALL NOT be
the mechanism, and the model SHALL NOT be the thing that parses a change source's
response: a tool result SHALL reach the model already typed.
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

#### Scenario: A cause is determinable without every channel being read
- **GIVEN** an incident whose change events account for the departure on their own
- **WHEN** the model answers having read changes and metrics but not logs
- **THEN** the determined `cause_type` is accepted, and the unread channel is not
  treated as missing evidence

### Requirement: The evidence behind a cause determination is recorded
The system SHALL record which retrieved evidence the verdict relied on, so a
human picking up the incident can tell what the determination was based on and
distinguish a well-evidenced call from a thin one. Since which channels were read is now
the model's choice, the record SHALL also make plain what was retrieved and what was
not.

#### Scenario: Supporting evidence accompanies a determined cause
- **GIVEN** the Investigator determines a cause for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the evidence the verdict relied on is recorded with it

#### Scenario: What was never read is distinguishable from what came back empty
- **GIVEN** an investigation in which the model never called the change-events tool
- **WHEN** the incident's record is examined
- **THEN** it shows that channel as unread, not as read and empty
