# write-mcp-server Specification

## Purpose
The write tier: the single process that may change the state of the Target
Environment, and the typed client through which agents reach it. Its existence
apart from `argus-read-mcp` is what makes "read-only" a property of a running
process rather than a convention its callers are trusted to observe.

## Requirements
### Requirement: A write-tier MCP server runs as its own process
The system SHALL run `argus-write-mcp` as a process separate from
`argus-read-mcp`, exposing the tools that change state. The read server SHALL
contain no code path that mutates anything and SHALL hold no credential that
could authorize one, so that the autonomy tier is a property of which process is
running rather than a convention its callers observe.

#### Scenario: The write server is reachable alongside the read server
- **GIVEN** the stack is up
- **WHEN** each MCP server is asked to list its tools
- **THEN** both answer, and the tool that changes flag state is offered by the
  write server and not by the read server

#### Scenario: The read server holds no credential that can change state
- **GIVEN** the configuration each server is started with
- **WHEN** the read server's configuration is inspected
- **THEN** it carries no credential able to change flag state, only one able to
  evaluate

### Requirement: The write server can set a feature flag's state
The write server SHALL expose a tool that sets a named feature flag on or off in
the flag provider's configured environment, returning once the provider reports
the flag as evaluating to the requested state. The tool SHALL report a flag it
could not change as a failure rather than as success. One tool serves both
directions, because undoing a flag change and undoing that undo are the same
operation with the state reversed.

#### Scenario: An enabled flag is turned off
- **GIVEN** a flag that is enabled in the provider
- **WHEN** the tool is called to set that flag off
- **THEN** the flag is off afterwards, as the provider reports it

#### Scenario: A disabled flag is turned on
- **GIVEN** a flag that is disabled in the provider
- **WHEN** the tool is called to set that flag on
- **THEN** the flag is on afterwards, as the provider reports it

#### Scenario: The tool returns only once the change is visible
- **GIVEN** a flag whose state is about to be changed
- **WHEN** the tool returns successfully
- **THEN** an evaluation of that flag made immediately afterwards reports the
  requested state

#### Scenario: An unreachable provider is a failure
- **GIVEN** the flag provider cannot be reached
- **WHEN** the tool is called
- **THEN** it reports a failure, and does not report the flag as changed

### Requirement: The write server reports recent flag changes
The write server SHALL expose a tool reporting the flag changes the provider
recorded in the configured environment since a given moment - for each, the flag,
the state it was changed to, when, and who by - so that an agent can identify
which flag an incident is about and in which direction it moved.

This read SHALL live on the write server rather than the read server: the
provider issues no credential that can read its change history without also being
able to change a flag, and issuing the read server such a credential would defeat
the tier split.

#### Scenario: A flag that was switched on is reported as such
- **GIVEN** a flag was enabled in the environment after the given moment
- **WHEN** the flag-change tool is called
- **THEN** it reports that flag, changed to enabled

#### Scenario: A flag that was switched off is reported as such
- **GIVEN** a flag was disabled in the environment after the given moment
- **WHEN** the flag-change tool is called
- **THEN** it reports that flag, changed to disabled

#### Scenario: Changes before the window are not reported
- **GIVEN** a flag was changed before the given moment and none since
- **WHEN** the flag-change tool is called
- **THEN** that change is absent from the result

#### Scenario: An unreachable provider is a failure, not an empty history
- **GIVEN** the flag provider cannot be reached
- **WHEN** the flag-change tool is called
- **THEN** it reports a failure rather than reporting that nothing changed

### Requirement: Each write tool is a typed function on a client package
The system SHALL expose every write tool as a typed function in a
`write_mcp_client` package installed into the agents that call it, rather than
requiring callers to name tools as strings and pass untyped payloads, so that a
mistyped tool name or argument is a static type error.

#### Scenario: A write tool is called through the typed client
- **GIVEN** the write server is running
- **WHEN** an agent calls the flag-revert function on `write_mcp_client`
- **THEN** the call succeeds and the flag is reverted

### Requirement: Every state-changing action carries an undo descriptor
The write server's state-changing tools SHALL return, with their result, a
descriptor recording the state that existed before the action, sufficient to
restore it. The descriptor SHALL name the prior state rather than the call that
would reverse it.

#### Scenario: Changing a flag records what it was
- **GIVEN** a flag about to be set to a new state
- **WHEN** the tool is called for it
- **THEN** the result carries a descriptor naming that flag, its environment, and
  the state it held before the call
