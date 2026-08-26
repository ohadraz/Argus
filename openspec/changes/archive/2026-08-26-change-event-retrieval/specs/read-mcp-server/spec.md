## ADDED Requirements

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
