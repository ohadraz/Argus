## MODIFIED Requirements

### Requirement: Investigator determines cause_type from the Target Service's current logs
The system SHALL retrieve logs via the `argus-read-mcp` server's
`get_log_lines` tool during investigation, windowed and anchored on the metric
onset, and SHALL retrieve the changes made to the service via that server's
`get_change_events` tool over a wider window. It SHALL determine a `cause_type`
by asking a real LLM to judge the retrieved evidence - metrics, logs and
changes together. Deterministic keyword matching SHALL NOT be the mechanism,
and the model SHALL NOT be the thing that parses a change source's response.
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

### Requirement: A bad deployment is a determinable cause
The system SHALL include a bad deployment among the causes it can determine,
identified from a retrieved deploy event rather than inferred from log prose.
A deploy that precedes the onset and is followed by a departure the deploy
plausibly explains SHALL be attributable as that cause.

#### Scenario: A deploy before a latency departure is attributed
- **GIVEN** the Target Service's active scenario is `bad-deployment`, whose
  deploy precedes a p95 latency departure
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as a bad deployment, at a confidence high
  enough to route to `mitigating`

#### Scenario: A flag-caused incident is not attributed to a deploy
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`, for
  which the change source reports no deploy
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as the feature flag toggle, not as a
  deployment

### Requirement: A change alone is not a cause
The system SHALL treat a retrieved change as a candidate explanation to be
judged against the symptoms, not as proof of causation. A change that does not
explain the observed departure SHALL NOT be reported as the cause merely
because it is the only change in the window.

#### Scenario: An unrelated change does not become the verdict
- **GIVEN** evidence containing a change that does not account for the
  observed symptoms
- **WHEN** the Investigator investigates
- **THEN** it does not report that change as the cause, and reporting no
  determined cause remains available
