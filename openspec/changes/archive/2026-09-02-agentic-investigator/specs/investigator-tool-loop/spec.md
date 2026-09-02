## ADDED Requirements

### Requirement: Investigation is a tool-use conversation, not a fixed sequence of reads

The system SHALL conduct an investigation as a multi-turn `tool_use` exchange with the
model. The loop SHALL offer the read tier's retrieval calls as tool definitions and
SHALL dispatch each tool call the model makes, returning its result as the next turn's
input. Which channel is read, over which window, and in what order SHALL be the model's
decision, not a plan computed before the model has seen anything.

#### Scenario: The model chooses which channel to read
- **GIVEN** an investigation whose opening message names an alert and its onset
- **WHEN** the model calls the change-events tool and then answers
- **THEN** the investigation reads change events, does not read log lines, and returns
  the model's answer

#### Scenario: A tool result feeds the next turn
- **GIVEN** a model that calls the log tool and then, having seen its lines, calls it
  again over an earlier window
- **WHEN** the investigation runs
- **THEN** both calls are dispatched in order, and the second call's window is the one
  the model asked for

### Requirement: Only the read tier's tools are offered

The system SHALL offer the Investigator exactly the retrieval tools of the read-only
tier and the answer tool below. No tool that changes state SHALL be present in the
Investigator's tool list. This SHALL hold by which client the loop possesses, not by
instructing the model to refrain.

#### Scenario: No write-tier tool is offered
- **GIVEN** an investigation about to open its conversation
- **WHEN** the tool definitions given to the model are inspected
- **THEN** they name only retrieval tools and the answer tool, and none of them can
  change a flag, a deployment, or a pull request

### Requirement: The investigation ends by the model calling a typed answer tool

The system SHALL provide a `final_answer` tool whose input schema is the ranked
hypotheses an investigation produces. The loop SHALL end when the model calls it, and
SHALL build its result from that call's arguments. Prose SHALL NOT be parsed for an
answer: a model that stops calling tools without calling `final_answer` SHALL be treated
as having produced no answer, not as having finished.

#### Scenario: Calling the answer tool ends the investigation
- **GIVEN** a model that has read some evidence and calls `final_answer` with two ranked
  hypotheses
- **WHEN** the loop receives that call
- **THEN** the investigation ends and returns those two hypotheses in the order given

#### Scenario: A model that stops talking has not answered
- **GIVEN** a model that returns a turn containing only text and no tool call
- **WHEN** the loop receives that turn
- **THEN** the investigation does not treat the text as an answer, and continues or
  reports no determined cause according to the remaining budget

### Requirement: A tool call that cannot be served is answered, not raised

The system SHALL return a failed or nonsensical tool call to the model as a tool result
describing what went wrong, rather than ending the investigation. A window that is
inverted, empty, or wider than the configured maximum SHALL be reported back so the
model can correct it. A failure of the underlying change source SHALL remain a failure
of the investigation, as it is today.

#### Scenario: An invalid window is reported back to the model
- **GIVEN** a model that requests a log window ending before it starts
- **WHEN** the loop dispatches that call
- **THEN** it returns a tool result saying the window was invalid, and the investigation
  continues

#### Scenario: A clamped window is reported as clamped
- **GIVEN** a model that requests a log window wider than the configured maximum span
- **WHEN** the loop dispatches that call
- **THEN** the lines returned are those of the clamped window, and the tool result says
  the requested span was clamped

#### Scenario: An unreachable change source still fails the investigation
- **GIVEN** a change source that cannot be reached
- **WHEN** the model calls the change-events tool
- **THEN** the investigation fails rather than continuing and reporting a cause drawn
  from the other channels

### Requirement: The conversation is narrated as it happens

The system SHALL publish an account of each tool call the model makes and each result it
receives, in order, so that an investigation can be reconstructed after the fact. The
account SHALL name the channel and the window requested. The investigation SHALL reach
the same conclusion whether or not anybody is listening.

#### Scenario: Each retrieval is narrated with its window
- **GIVEN** an investigation in which the model reads logs twice over different windows
- **WHEN** the published events are examined
- **THEN** both reads appear, in order, each naming the window that was requested

#### Scenario: A silent publisher changes nothing
- **GIVEN** two identical investigations, one with a publisher and one without
- **WHEN** both run against the same scripted turns
- **THEN** both return the same result
