## ADDED Requirements

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
