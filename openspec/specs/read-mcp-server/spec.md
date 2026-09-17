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

### Requirement: The read server reports which flags are enabled
The read server SHALL expose a tool reporting which flags are currently enabled
in the configured environment, evaluated at the moment of the call, so that an
agent can identify the flag an incident is about without that flag being named
in Argus's own configuration.

#### Scenario: An enabled flag is reported
- **GIVEN** exactly one flag is enabled in the environment
- **WHEN** the enabled-flags tool is called
- **THEN** it returns that flag

#### Scenario: A reverted flag stops being reported
- **GIVEN** a flag was enabled and has since been turned off
- **WHEN** the enabled-flags tool is called
- **THEN** that flag is absent from the result

### Requirement: The service's own source is a read channel
The system SHALL serve the Target Service's repository as two read tools - what
files there are at a ref, and what one of them says - under a credential that
can read a repository and cannot write to one. A repository becoming visible to
the read tier SHALL NOT make the read tier capable of changing it (§13).

#### Scenario: The files of a repository are listed
- **WHEN** the repository is listed at a ref
- **THEN** every file is named as a path from the root, and directories are left
  out

#### Scenario: A file is read as the text it holds
- **WHEN** a path is read at a ref
- **THEN** its whole contents come back as text

#### Scenario: The read credential cannot write
- **WHEN** the read tier's configuration is examined
- **THEN** the credential it holds for the repository grants reading only, and
  no tool on this server changes a repository

### Requirement: A listing that is not whole is refused
The system SHALL raise rather than answer when the repository could not be read
in full - including when the provider truncated its own listing. A listing
missing files is indistinguishable from a repository that does not have them,
and a fix would be written for the wrong file.

#### Scenario: A truncated listing is refused
- **GIVEN** a repository large enough that the provider truncates its answer
- **WHEN** the files are listed
- **THEN** the call fails, naming the truncation, rather than returning a short
  list

#### Scenario: A path that is not there is said to be missing
- **WHEN** a path that does not exist is read
- **THEN** the call fails, rather than answering with an empty string - a file
  that exists and says nothing is a real thing, and the two must not arrive
  looking alike

#### Scenario: A file that is not text is refused
- **WHEN** a path holding an image or an archive is read
- **THEN** the call fails rather than returning replacement characters that
  reach a model looking like code

### Requirement: argus-read-mcp exposes search_repository_by_meaning over MCP
The read server SHALL expose retrieval by meaning over the Target Service's
source as an MCP tool, taking a description and a limit, and SHALL answer the
nearest passages with their paths and line spans. The tool SHALL live on the
read tier, under the credential that cannot write, beside the three channels
that already read the repository.

The registration SHALL hold no behavior: what it does lives in the module that
owns retrieval, as `get_log_lines`, `get_change_events` and `search_repository`
already do.

#### Scenario: The tool is on the read server
- **WHEN** the read server's tools are enumerated
- **THEN** retrieval by meaning is among them, and nothing on that server writes

#### Scenario: The registration delegates
- **WHEN** the tool is called
- **THEN** it calls the retrieval module and returns what it answered

### Requirement: The typed client exposes the meaning-retrieval tool
The client package SHALL expose the tool as a typed function taking the
description, the limit and the connection, rather than a stringly-typed tool
call, as it does for every other tool on this server.

#### Scenario: A caller gets a function, not a tool name
- **WHEN** a calling agent retrieves by meaning
- **THEN** it calls a typed function whose parameters are checked statically
