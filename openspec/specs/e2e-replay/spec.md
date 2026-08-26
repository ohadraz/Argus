# e2e-replay Specification

## Purpose
The end-to-end pipeline verified against recorded model answers - free, keyless, and run on every push. It proves the pipeline works; whether the model reaches the right conclusion is measured by the eval suite instead.
## Requirements

### Requirement: The end-to-end pipeline is verifiable without spending a token
The system SHALL provide a way to run the end-to-end suite against the full
local stack with every model answer replayed from a stored recording, so that
the pipeline - webhook, orchestrator graph, retrieval over MCP, adapter,
persistence, terminal status - is verified without an API key and without cost.

Selecting the replay path SHALL be configuration, not a code branch. Nothing in
the production path may test for whether it is being replayed.

#### Scenario: The suite runs with no API key configured
- **GIVEN** no Anthropic API key is available
- **WHEN** the replay end-to-end suite runs
- **THEN** the incidents reach their expected terminal statuses, and no request
  is made to the real Anthropic API

#### Scenario: The same tests serve both paths
- **GIVEN** the end-to-end cases
- **WHEN** they are run against the real API, and against the recordings
- **THEN** the same test bodies and the same assertions serve both, with no
  case that exists only for one

### Requirement: A replayed answer is arranged where the reader is looking
The system SHALL have each end-to-end case state which recording answers it,
beside the step that seeds the Target Service's scenario. A reader SHALL be
able to see both stand-ins arranged in the same place, rather than having one
supplied invisibly by a fixture.

The seeded answer SHALL remain available for every model call the investigation
makes, so that a widening loop is not the thing that decides whether a test
passes.

#### Scenario: The recording is named in the test's arrangement
- **GIVEN** an end-to-end case for a scenario
- **WHEN** its arrangement is read
- **THEN** it names both the Target Service scenario and the recording that
  answers for the model

#### Scenario: A widening investigation does not exhaust the seeded answer
- **GIVEN** an investigation that asks the model more than once
- **WHEN** it runs against the recordings
- **THEN** every call is answered, and the outcome does not depend on how many
  iterations the loop happened to take

### Requirement: The replay path runs on every push
The system SHALL run the replay end-to-end suite in continuous integration on
every push, alongside the checks that already run there. The paid end-to-end
suite SHALL remain a manual trigger, because it answers a different question -
whether the model reaches the right conclusion - and spends tokens to do it.

#### Scenario: A broken pipeline fails the push
- **GIVEN** a change that breaks the path between the webhook and a terminal
  incident status
- **WHEN** it is pushed
- **THEN** continuous integration fails, without a human having triggered
  anything

#### Scenario: The paid suite is not triggered by a push
- **GIVEN** a push to any branch
- **WHEN** continuous integration runs
- **THEN** no suite that reaches the real Anthropic API is started

### Requirement: The replay path announces itself where it is read
The system SHALL state, at each place a reader encounters this path - the
session that runs it, the continuous-integration job that invokes it, and the
tests themselves - that it is the CI path and that every model answer is
replayed from a recording rather than asked for.

A suite that looks like it proves the model works, but does not, is worse than
no suite: it invites a reader to trust a conclusion nothing checked.

#### Scenario: The session says what it does and does not prove
- **GIVEN** the session that runs the replay suite
- **WHEN** its documentation is read
- **THEN** it states that answers are replayed, that no token is spent, and
  that the model's judgement is measured elsewhere

#### Scenario: The CI job says why it is free
- **GIVEN** the continuous-integration job that runs the replay suite
- **WHEN** its definition is read
- **THEN** it states that it is keyless and costs nothing, and why that lets it
  run on every push
