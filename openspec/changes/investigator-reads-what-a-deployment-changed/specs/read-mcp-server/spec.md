# read-mcp-server Specification (delta)

## ADDED Requirements

### Requirement: argus-read-mcp exposes what a deployment changed over MCP

The system SHALL expose a tool on `argus-read-mcp` answering what one deployment
of a named service changed, taking the service and the deployment's revision and
nothing else. Both halves of the answer SHALL be assembled in the server: the
revision deployed before the named one is read from the deployment history, and
the difference between the two is read from the repository.

Both integrations SHALL stay behind the port, so that no calling agent holds a
deployment-history client or a repository client of its own, and the tool SHALL be
read-only like the rest of that server's surface - it holds a credential that can
read a repository and one that can read a deployment's history, and neither can
change either.

#### Scenario: The tool answers from a revision and a service alone
- **GIVEN** the deployment history records a revision preceded by another, and the
  repository can be compared
- **WHEN** the tool is called with the service and the later revision
- **THEN** it returns what that deployment changed, without the caller naming the
  earlier revision

#### Scenario: The tool exposes no vendor detail
- **GIVEN** a caller of the tool
- **WHEN** it inspects the answer
- **THEN** nothing in it names or shapes itself after the deployment system or the
  repository host

#### Scenario: A repository that cannot be compared raises rather than answering emptily
- **GIVEN** a repository the server cannot reach
- **WHEN** the tool is called
- **THEN** it raises, and does not answer that the deployment changed nothing

### Requirement: The typed client exposes the deployment-diff tool

The system SHALL expose the deployment-diff tool from `read_mcp_client` as a typed
Python function performing a real MCP call, matching how the client already
exposes the server's other tools.

#### Scenario: Calling the deployment-diff tool through its typed client succeeds
- **GIVEN** the `argus-read-mcp` server is running, and its deployment history and
  repository are both reachable
- **WHEN** the typed client function is called with a service and a revision
- **THEN** it returns what that deployment changed, without raising
