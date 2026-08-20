## Why

The Investigator currently calls the Target Service's `GET /logs` directly over
`httpx`, bypassing MCP entirely (an explicit walking-skeleton shortcut - see
`argus_core.mcp.StubMCPClient`). A real ReAct loop needs real tools to react
over; standing up Argus's first real MCP server now - before ReAct - gives the
Investigator a genuine MCP tool and keeps the ReAct change scoped to reasoning,
not plumbing.

## What Changes

- New `read_mcp_server` module: `argus-read-mcp`, the read-only half of the
  tier-split MCP topology (spec §12.1). This change gives it its first tool,
  `get_log_lines(window, filters)`, which fetches the Target Service's full log
  via HTTP and does the windowing/filtering/capping itself (spec §16) - logic
  that doesn't exist anywhere today (`GET /logs` returns everything,
  unfiltered). Its remaining read tools (metrics, flag evaluation, memory
  query, Slack reads) arrive with the changes that need them.
- New `read_mcp_client` module: the typed client package paired with that
  server, exposing `get_log_lines(window, filters) -> list[str]` as a real
  Python function rather than a stringly-typed `call_tool(name, **kwargs)`.
- `argus_core.mcp` is reduced to the shared streamable-HTTP transport
  (`call_mcp_tool`) that every typed client package wraps, and renamed to
  `argus_core.mcp_transport`; the placeholder
  `MCPClient`/`StubMCPClient`/`get_mcp_client` trio is removed, having no
  remaining callers.
- `agent_investigator` depends on `argus-read_mcp_client` and its `_fetch_logs`
  calls `get_log_lines()` instead of hitting the Target Service directly.
- `noxfile.py`'s `e2e` session gains a local `read_mcp_server` process
  (uvicorn, same pattern as the existing `_start_argus_web`/`_stop_argus_web`
  helpers - `argus_web` itself isn't containerized either) so the existing e2e
  stack actually has something to call.

## Capabilities

### New Capabilities
- `read-mcp-server`: `argus-read-mcp`, the read-only MCP server, and its typed
  client package - exposing `get_log_lines(window, filters)` over the
  streamable-HTTP transport.

### Modified Capabilities
- `investigator-cause-detection`: the Investigator now retrieves logs via the
  `read-mcp` `get_log_lines` tool instead of calling the Target Service's
  `GET /logs` directly. Observable cause-detection behavior (keyword matching,
  confidence, persisted `cause_type`) is unchanged - only how logs are fetched.

## Impact

- New modules: `modules/read_mcp_server/`, `modules/read_mcp_client/` (each own
  `pyproject.toml`, `src/`, `tests/`).
- Modified: `modules/argus_core/src/argus_core/mcp.py` (renamed to
  `mcp_transport.py`),
  `modules/argus_core/src/argus_core/config.py` (adds `read_mcp_host`/
  `read_mcp_port` plus a composed `read_mcp_url` property),
  `modules/agent_investigator/src/agent_investigator/__init__.py`,
  `noxfile.py`.
- No new e2e test needed: the existing
  `test_investigator_diagnoses_a_feature_flag_toggle_as_the_cause` e2e already
  drives the full webhook -> orchestrator -> Investigator -> DB path and will
  exercise `read-mcp` once it's wired in, as long as `nox -s e2e` starts it
  alongside `argus_web`.
