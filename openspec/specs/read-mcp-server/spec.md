# read-mcp-server Specification

## Purpose
TBD - created by archiving change read-mcp-server. Update Purpose after archive.
## Requirements
### Requirement: argus-read-mcp exposes get_log_lines over MCP
The system SHALL provide a FastMCP server, `argus-read-mcp`, exposing a
`get_log_lines(alert_time, window_start, window_end, filters)` tool that
fetches the Target Service's current log via HTTP and returns the entries
matching the requested window and filters.

#### Scenario: get_log_lines returns the Target Service's current log
- **GIVEN** the Target Service has log entries available at `GET /logs`
- **WHEN** `get_log_lines` is called with no alert time, window or `filters`
- **THEN** it returns those log entries as a list of strings

#### Scenario: get_log_lines reflects the Target Service's active scenario
- **GIVEN** a scenario is active on the Target Service
- **WHEN** `get_log_lines` is called
- **THEN** the returned lines match that scenario's currently seeded log
  entries

### Requirement: A typed client package exposes the read server's tools
The system SHALL provide a `read_mcp_client` package, separate from the server
package, exposing each of `argus-read-mcp`'s tools as a typed Python function
that performs a real MCP call over the streamable-HTTP transport.

#### Scenario: Calling the read server through its typed client succeeds
- **GIVEN** the `argus-read-mcp` server is running
- **WHEN** `read_mcp_client.get_log_lines()` is called
- **THEN** it returns the Target Service's current log lines, without raising

#### Scenario: Consuming the client does not require the server package
- **GIVEN** a module that calls `argus-read-mcp` tools
- **WHEN** its dependencies are declared
- **THEN** it depends on `read_mcp_client` only, not on `read_mcp_server`


### Requirement: argus-read-mcp exposes get_change_events over MCP
The system SHALL expose a `get_change_events(service, window_start, window_end)`
tool on `argus-read-mcp`, returning the changes made to that service within
that window as structured records. The window SHALL be explicit and required,
with no alert-time default: how far back a cause may lie is the caller's
judgement, not retrieval's. The vendor integration behind it SHALL live in the
server, so that no calling agent holds one of its own, and the tool SHALL be
read-only like the rest of that server's surface.

#### Scenario: get_change_events returns the changes in its window
- **GIVEN** the change source reports changes at known times
- **WHEN** `get_change_events` is called with a window covering some of them
- **THEN** it returns exactly those changes, as structured records

#### Scenario: The tool exposes no vendor detail
- **GIVEN** a caller of `get_change_events`
- **WHEN** it inspects the returned records
- **THEN** nothing in them names or shapes itself after the system that
  reported the change

### Requirement: The typed client exposes the change-event tool
The system SHALL expose `get_change_events` from `read_mcp_client` as a typed
Python function performing a real MCP call, matching how the client already
exposes the server's other tools.

#### Scenario: Calling the change-event tool through its typed client succeeds
- **GIVEN** the `argus-read-mcp` server is running and its change source is
  reachable
- **WHEN** `read_mcp_client.get_change_events(...)` is called
- **THEN** it returns the change events for the requested window, without
  raising
