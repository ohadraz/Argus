## Context

`agent_investigator.investigate()` reached the Target Service's `GET /logs`
directly via `httpx` (see `investigator-hypothesis-loop`'s design.md, which
explicitly deferred this: "Building a real MCP server first would be a
substantially larger, separately-scoped change"). `argus_core.mcp` existed only
as a placeholder shape (`StubMCPClient.call_tool` raising
`NotImplementedError`) - no module had ever made a real MCP call.

The spec (§12.1) defines two FastMCP servers split by autonomy tier -
`argus-read-mcp` and `argus-write-mcp` - each paired with a typed client
package. This change builds the read server and its client, with the single
tool the Investigator needs today. `argus-write-mcp`, the remaining read tools,
and the ReAct loop that would drive real time-windowed, bucket-scoped queries
(§16) don't exist yet.

## Goals / Non-Goals

**Goals:**
- Stand up `argus-read-mcp` as a real, independently-deployable FastMCP server
  exposing `get_log_lines(window, filters)`.
- Add its paired typed client package, establishing the server/client pattern
  every future MCP server follows.
- Make `agent_investigator.investigate()` call it instead of hitting the Target
  Service directly, with zero change to observable cause-detection behavior
  (spec `investigator-cause-detection` still holds).

**Non-Goals:**
- Real time-windowing or `bucket_ids`-scoped filtering per §16's full two-phase
  design - that needs the metrics tool (to produce anomalous buckets) and the
  ReAct loop (to drive iterative queries), neither of which exists yet.
  `window`/`filters` are accepted on the signature so it matches the spec's
  shape, but `agent_investigator` calls it with no constraints for now (full
  log, same as today).
- Pagination for oversized results - out of scope until a caller needs
  windowed/capped results.
- `argus-write-mcp`, and the read server's other tools (metrics, flag
  evaluation, memory query, Slack reads) - each arrives with the change that
  needs it.
- The ReAct loop itself (a separate, later change).

## Decisions

**New top-level `modules/read_mcp_server/` and `modules/read_mcp_client/`
packages.** Matches the spec's "each a network-facing, independently
deployable module" (§12.1, §20.1) and this workspace's flat one-level module
discovery (`modules/*/pyproject.toml`). Both depend on `argus_core` via
`{ workspace = true }`; neither is depended on *by* `argus_core`, keeping the
shared library at the bottom of the dependency graph.

**Server and client are separate packages, not one package with two
submodules.** The server is a deployed process; the client is a library
installed into calling agents. Keeping them separate means a consumer of the
client (e.g. `agent_investigator`) never pulls server-only code - or a
transitive dependency on the server's own deps - into its dependency graph.

**The client exposes typed functions, not a generic `call_tool`.** A
stringly-typed `call_tool("get_log_lines", **kwargs)` puts the tool name and
argument names beyond mypy's reach - a typo is a runtime failure discovered
mid-incident, and every caller has to `cast` an `object` return. The typed
wrapper (`get_log_lines(window, filters) -> list[str]`) makes both static. The
generic streamable-HTTP transport underneath is genuinely shared, so it stays
in `argus_core.mcp_transport` as `call_mcp_tool`, wrapped once per tool per client
package.

**`argus_core.mcp`'s `MCPClient`/`StubMCPClient`/`get_mcp_client` are removed,
and what remains is renamed to `argus_core.mcp_transport`.** Once `read-mcp`
had a typed client, the string-dispatched
`get_mcp_client(server)` had zero callers workspace-wide. It was
walking-skeleton scaffolding for an approach this change replaces; keeping it
speculatively for servers that don't exist yet would leave a second, untyped
way to call MCP tools sitting next to the typed one. The module is named for
its role (the transport) rather than its position in the dependency graph -
`argus_core` already conveys "shared", and the clients call it rather than
inherit from it, so a `base_`-style name would be misleading.

**The injection seam for the tool's HTTP fetch lives on a private helper, not
on the `@mcp.tool()`-decorated function.** A `Callable`-typed default
parameter on a decorated tool breaks FastMCP's JSON-schema generation
(verified directly: `pydantic.errors.PydanticInvalidForJsonSchema: Cannot
generate a JsonSchema for core_schema.CallableSchema`), since every tool
parameter must be JSON-schema-representable. The tool delegates to
`_get_log_lines(fetch=...)`, which carries the seam.

**`read_mcp_host`/`read_mcp_port` settings with a composed `read_mcp_url`
property**, mirroring the existing `database_*` fields and `database_url`.
Host and port are what actually vary per environment; the URL is derived, and
tests override the parts rather than reconstructing the whole string.

**`argus-read-mcp` runs as a local uvicorn process started by the `e2e` nox
session, not a `docker-compose.yml` service.** `argus_web` already isn't
containerized - `noxfile.py`'s `e2e` session starts it directly via
`_start_argus_web`/`_wait_for_argus_web`/`_stop_argus_web`, a decision already
recorded as deliberate. The read server gets the equivalent trio, started and
torn down alongside `argus_web` in the same `try`/`finally`, rather than
introducing a second infrastructure pattern for one more in-process Python
service.

## Risks / Trade-offs

- **`get_log_lines(window, filters)` ignoring both params reads as "half a
  tool."** Mitigation: the deferral is documented in the function's docstring,
  the same pattern `agent_investigator.investigate()` uses for its own no-ReAct
  deferral.
- **No new e2e test covers the read server directly.** The existing
  `test_investigator_diagnoses_a_feature_flag_toggle_as_the_cause` e2e proves
  the wiring end-to-end once the server is started alongside `argus_web`; if
  that startup step is missing, the failure mode is a loud connection error,
  not a silent pass. One integration test in `read_mcp_client` additionally
  covers the real client-server round trip in isolation, against a stub Target
  Service, so a failure in just the MCP wiring is diagnosable without the full
  stack.
- **The integration test starts a real subprocess and binds two local ports.**
  Slower than a unit test (~1.4s) and could collide with a developer already
  running something on those ports. Accepted: mocking the transport would
  prove only the request shape, not that the call reaches a real server, which
  is the whole point of this change.

## Migration Plan

No data migration. Deployment-only: wire the read server's startup/teardown
into `noxfile.py`'s `e2e` session before or alongside the `agent_investigator`
change that starts calling it, so `nox -s e2e` never runs a stack where the
Investigator calls a service that isn't running.

## Open Questions

None outstanding - scope confirmed with the user (no new e2e needed; real
windowing deferred to the change that introduces the metrics tool / ReAct).
