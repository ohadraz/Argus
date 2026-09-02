# investigation-budget Specification

## Purpose
TBD - created by archiving change agentic-investigator. Update Purpose after archive.
## Requirements
### Requirement: The loop bounds the investigation in three independent dimensions

The system SHALL bound every investigation by a configured maximum number of tool calls,
a configured maximum cumulative token spend, and a configured maximum wall-clock
duration. Each SHALL be checked by the loop between turns, and whichever binds first
SHALL end the investigation. No single bound SHALL be relied on to imply the others: a
wide window is cheap in calls and expensive in tokens, and a narrow one is the reverse.

#### Scenario: The tool-call bound ends the investigation
- **GIVEN** a configured maximum of three tool calls
- **WHEN** the model makes a fourth tool call without having answered
- **THEN** the investigation ends without dispatching it

#### Scenario: The token bound ends the investigation
- **GIVEN** an investigation whose cumulative token usage passes the configured maximum
- **WHEN** the loop checks between turns
- **THEN** the investigation ends, even though tool calls and wall-clock remain

#### Scenario: The wall-clock bound ends the investigation
- **GIVEN** an investigation running past its configured maximum duration
- **WHEN** the loop checks between turns
- **THEN** the investigation ends, even though tool calls and tokens remain

### Requirement: The budget is enforced by the loop and is not the model's to extend

The system SHALL enforce every bound in code, outside the model's reach. No tool SHALL
allow the model to request more budget, and no instruction to the model SHALL be the
mechanism by which a bound holds. A model that ignores every hint SHALL still be stopped
at the bound.

#### Scenario: A model that never answers is still stopped
- **GIVEN** a model that calls a retrieval tool on every turn and never calls
  `final_answer`
- **WHEN** the investigation runs
- **THEN** it ends at the first bound reached, having made no more tool calls than the
  configured maximum

### Requirement: Metrics are read once before the model's first turn

The system SHALL read the metrics summary itself, before opening the conversation, and
SHALL locate the onset from that read. The model SHALL NOT be able to skip it. The model
MAY read metrics again over a different window; that is an ordinary tool call and is
counted against the budget like any other.

#### Scenario: Metrics are read even when the model asks for logs first
- **GIVEN** a model whose first turn calls the log tool
- **WHEN** the investigation runs
- **THEN** the metrics summary was already retrieved and an onset located before that
  first turn

#### Scenario: No anomalous minute ends the investigation before the model is asked
- **GIVEN** a metrics summary in which no minute departs from the baseline
- **WHEN** the investigation runs
- **THEN** it reports no determined cause, and the conversation with the model is never
  opened

### Requirement: A spent budget reports which bound was reached

The system SHALL report an investigation that ended on a bound as having no determined
cause and no confidence, distinguishable from a confident answer, and SHALL name which
bound ended it. Running out of time and reading everything without finding a cause call
for different human responses and SHALL NOT be reported alike.

#### Scenario: Exhaustion names the bound
- **GIVEN** an investigation that ends because its wall-clock bound was reached
- **WHEN** its result is examined
- **THEN** it carries no cause type and no confidence, and its summary says the time
  bound ended it

#### Scenario: A bound is not a crash
- **GIVEN** an investigation that ends on any bound
- **WHEN** its result is returned
- **THEN** it is an ordinary result the caller can act on, not a raised error

### Requirement: The model is warned before a bound binds

The system SHALL tell the model, in the tool result of the last turn before a bound
would bind, that it has one turn left. This SHALL be a hint only: the loop SHALL cut at
the bound regardless of what the model does with the warning.

#### Scenario: The last turn carries a warning
- **GIVEN** an investigation one tool call short of its configured maximum
- **WHEN** that call's result is returned to the model
- **THEN** the result says this is the final turn available

#### Scenario: Ignoring the warning does not extend the budget
- **GIVEN** a model that receives the final-turn warning and calls a retrieval tool
  anyway
- **WHEN** the loop receives that call
- **THEN** the investigation ends without dispatching it
