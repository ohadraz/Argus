## ADDED Requirements

### Requirement: Which retrieval channel the agent gets is configured
The system SHALL assemble the agent's retrieval tools from configuration -
substring search, retrieval by meaning, or both - and SHALL retain both
implementations whichever is configured. Neither SHALL replace the other, so
that which one localizes a fault better on a given repository stays a question
the benchmark can put rather than one the code has already answered.

#### Scenario: The agent is offered what it was configured to have
- **GIVEN** retrieval by meaning is the configured channel
- **WHEN** the agent's tools are assembled
- **THEN** the meaning channel is among them, and the loop is otherwise unchanged

#### Scenario: Both channels can be offered at once
- **GIVEN** both channels are configured
- **WHEN** the agent's tools are assembled
- **THEN** it may search by substring and by meaning within the same attempt

#### Scenario: Neither implementation is removed
- **WHEN** the retrieval implementations available to the agent are enumerated
- **THEN** both substring search and retrieval by meaning are present, whatever
  is configured

### Requirement: The agent is told when what it searched is behind
The system SHALL state in the agent's opening message, as a fact rather than a
caveat, when the index it will search describes an earlier commit than the
deployed branch, naming the commit indexed and the commit deployed. The agent
SHALL NOT be left to infer this from what it reads.

A limitation the model cannot detect from the inside is stated to it, on the same
rule the investigation loop follows for a bound it cannot see: a model reading
passages from an earlier commit reports the same confidence as one reading
current code, because it cannot miss what it was never shown.

#### Scenario: A behind index is stated up front
- **GIVEN** the index describes an earlier commit than the deployed branch
- **WHEN** the agent is opened
- **THEN** the message states that the code it can retrieve may not be the code
  deployed, and names both commits

#### Scenario: A current index is not remarked on
- **GIVEN** the index describes the deployed commit
- **WHEN** the agent is opened
- **THEN** the message says nothing about staleness

### Requirement: A retrieval channel that failed is not a failed attempt
The system SHALL answer a failed retrieval call as a tool result the agent reads,
as it does for every other tool, and SHALL NOT end the attempt on one. An agent
offered both channels SHALL be able to fall back to the other.

#### Scenario: An unreachable index costs one turn
- **GIVEN** the vector store cannot be reached
- **WHEN** the agent retrieves by meaning
- **THEN** it is told the call failed, keeps the turns it has left, and may
  search by substring instead
