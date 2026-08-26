## ADDED Requirements

### Requirement: The loop retrieves change events as a third input
The system SHALL retrieve the changes made to the service before investigating,
once per investigation over the configured change lookback, and SHALL include
them in the evidence shown to the model alongside the metric buckets and the
log lines. The retrieval SHALL happen once rather than per iteration, for the
same reason the metrics summary does: the window is already wide and the rows
are sparse, so re-reading returns what was already read.

The change window SHALL end at the onset and reach back from it by the
configured lookback. A change made after the incident began did not begin it,
and offering it as a candidate invites attribution by mere proximity.

#### Scenario: The change window ends at the onset
- **GIVEN** a metrics summary whose earliest anomalous bucket is at some minute
- **WHEN** the Investigator retrieves change events
- **THEN** the requested window ends at that minute and starts the configured
  change lookback before it

#### Scenario: Change events reach the model as evidence
- **GIVEN** a change source reporting a change before the incident's onset
- **WHEN** the Investigator asks the model for a hypothesis
- **THEN** the evidence it shows includes that change event

#### Scenario: Changes are retrieved once across a widening investigation
- **GIVEN** an investigation that runs more than one iteration
- **WHEN** its retrieval calls are counted
- **THEN** change events were retrieved once, while log lines were retrieved
  once per iteration

#### Scenario: A cause older than the log window is still visible
- **GIVEN** a change that occurred further before the onset than any log window
  the loop is permitted to request
- **WHEN** the Investigator investigates
- **THEN** that change is still among the evidence shown to the model

### Requirement: A failed change retrieval stops the investigation rather than shrinking it
The system SHALL let a change-source failure surface as a failure, and SHALL
NOT continue with logs alone while reporting a cause as though the change
evidence had been seen and found empty.

#### Scenario: An unreachable change source does not become a quiet logs-only investigation
- **GIVEN** a change source that cannot be reached
- **WHEN** the Investigator investigates
- **THEN** the investigation fails rather than producing a hypothesis drawn
  from logs alone
