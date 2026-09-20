# investigator-cause-detection Specification

## Purpose
TBD - created by archiving change investigator-hypothesis-loop. Update Purpose after archive.
## Requirements
### Requirement: Investigator determines failure_mode from the Target Service's current logs
The system SHALL make the `argus-read-mcp` server's `get_log_lines` and
`get_change_events` tools available to the model during investigation, and SHALL
dispatch them when the model calls them. It SHALL determine a `failure_mode`
by asking a real LLM to judge the evidence it retrieved - metrics, logs and
changes, whichever of them it chose to read. Deterministic keyword matching SHALL NOT be
the mechanism, and the model SHALL NOT be the thing that parses a change source's
response: a tool result SHALL reach the model already typed.
An undetermined cause SHALL be reported at a confidence below the mitigate
threshold.

#### Scenario: Feature-flag-toggle logs are recognized
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `failure_mode = "feature-flag-toggle"` at a confidence
  high enough to route to `mitigating`

#### Scenario: No recognizable logs report an undetermined cause, not a confident one
- **GIVEN** the Target Service has no active scenario (`get_log_lines`
  returns an empty list)
- **WHEN** the Investigator investigates the incident
- **THEN** it records a hypothesis with `failure_mode` left undetermined
  (`NULL`), at a confidence below the mitigate threshold, and the incident
  routes to `escalated` rather than to `mitigating`

#### Scenario: A cause is determinable without every channel being read
- **GIVEN** an incident whose change events account for the departure on their own
- **WHEN** the model answers having read changes and metrics but not logs
- **THEN** the determined `failure_mode` is accepted, and the unread channel is not
  treated as missing evidence

### Requirement: failure_mode is persisted on the hypothesis row
The system SHALL write the determined `failure_mode` (or leave it `NULL` if undetermined) to the `hypothesis` table's `failure_mode` column, in addition to `description` and `confidence`.

#### Scenario: A determined cause is persisted
- **GIVEN** the Investigator determines `failure_mode = "feature-flag-toggle"` for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the `hypothesis` row for that incident has `failure_mode = 'feature-flag-toggle'`

### Requirement: The evidence behind a cause determination is recorded
The system SHALL record which retrieved evidence the verdict relied on, so a
human picking up the incident can tell what the determination was based on and
distinguish a well-evidenced call from a thin one. Since which channels were read is
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

