## ADDED Requirements

### Requirement: Change events are retrievable for a time window
The system SHALL expose a read-only tool that returns the changes made to a
named service within a given time window, as structured records rather than as log
text. The tool SHALL be part of the read-only MCP surface, alongside log and
metric retrieval, so that no agent holds a vendor integration of its own.

#### Scenario: Changes inside the window are returned
- **GIVEN** a change source reporting changes at several times
- **WHEN** change events are requested for a window covering some of them
- **THEN** exactly the changes that occurred within that window are returned

#### Scenario: A window with no changes returns nothing
- **GIVEN** a change source reporting no change within the requested window
- **WHEN** change events are requested
- **THEN** an empty result is returned, and it is not an error

### Requirement: A change event is vendor-neutral
The system SHALL represent every retrieved change in one model that names the
kind of change, when it took effect, and what it referred to - independent of
which system reported it. Nothing above the retrieval boundary SHALL depend on
the reporting system's own response shape.

#### Scenario: A deploy is represented as a change event
- **GIVEN** a change source reporting a completed deploy
- **WHEN** it is retrieved
- **THEN** the result names the change kind as a deploy, carries the time it
  took effect and the revision it deployed, and carries no field belonging to
  the reporting system's wire format

#### Scenario: The kind distinguishes one change from another
- **GIVEN** change events of more than one kind
- **WHEN** they are examined
- **THEN** each carries the kind of change it represents, so that a deploy and
  a configuration change are distinguishable without reading their text

### Requirement: An unreachable change source is an error, not an empty answer
The system SHALL fail loudly when the change source cannot be reached or
answers with an error, and SHALL NOT report "no changes" in that case. Silence
and absence are opposite facts, and reporting one as the other would let an
outage become evidence that nothing changed.

#### Scenario: An unreachable source raises rather than returning nothing
- **GIVEN** a change source that cannot be reached
- **WHEN** change events are requested
- **THEN** the request fails with an error naming the unreachable source, and
  no empty result is produced

#### Scenario: An error response is not mistaken for an empty history
- **GIVEN** a change source answering with an error status
- **WHEN** change events are requested
- **THEN** the request fails, and the failure is distinguishable from a window
  that genuinely contained no changes

### Requirement: The change window is wider than the log window and read once
The system SHALL retrieve change events over a configured lookback that is
independent of, and wider than, the log window, and SHALL read them once per
investigation rather than once per iteration. Changes are sparse, so a wide
window is affordable where the same width in logs is not.

#### Scenario: The change lookback is configured independently
- **GIVEN** a configured change lookback
- **WHEN** change events are retrieved for an incident
- **THEN** the requested window spans that lookback, regardless of the log
  window's current width

#### Scenario: Widening the log window does not re-read changes
- **GIVEN** an investigation that runs more than one iteration
- **WHEN** its retrieval calls are counted
- **THEN** change events were retrieved once, while log lines were retrieved
  once per iteration
