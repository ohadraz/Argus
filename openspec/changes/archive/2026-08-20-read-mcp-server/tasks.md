## 1. read_mcp_server module scaffolding

- [x] 1.1 Create `modules/read_mcp_server/pyproject.toml` (own package,
      depends on `argus_core` via `{ workspace = true }`, plus `mcp` and
      `httpx`)
- [x] 1.2 Create `modules/read_mcp_server/src/read_mcp_server/` package
      skeleton

## 2. get_log_lines implementation

- [x] 2.1 Implement `get_log_lines(window, filters)` as a FastMCP tool:
      fetches the Target Service's `GET /logs` and returns the lines
      unfiltered for this slice (per design.md's Non-Goals - `window`/
      `filters` accepted but not yet acted on), delegating to a private
      helper that carries the `fetch` injection seam
- [x] 2.2 Propose unit tests for the pass-through fetch behavior (per
      `tests/` TDD policy - test text proposed in chat, not written directly)

## 3. read_mcp_client module

- [x] 3.1 Create `modules/read_mcp_client/` as its own package, exposing
      `get_log_lines(window, filters) -> list[str]` as a typed function in
      `client.py`, re-exported from a thin `__init__.py`
- [x] 3.2 Reduce `argus_core.mcp` to the shared `call_mcp_tool`
      streamable-HTTP transport and rename it to `argus_core.mcp_transport`,
      removing the now-callerless
      `MCPClient`/`StubMCPClient`/`get_mcp_client` trio
- [x] 3.3 Add `read_mcp_host`/`read_mcp_port` settings with a composed
      `read_mcp_url` property, mirroring `database_url`
- [x] 3.4 Propose an integration test (not unit - a mocked transport would
      only prove the request shape, not that the call reaches a real server)
      that starts the real server against a stub Target Service and calls it
      through `read_mcp_client.get_log_lines()`

## 4. Wire agent_investigator to the read server

- [x] 4.1 Depend on `argus-read_mcp_client` and replace
      `agent_investigator._fetch_logs`'s direct `httpx.get` call with
      `get_log_lines()`
- [x] 4.2 Confirm existing `agent_investigator` unit tests (which inject a
      stub `fetch_logs`) still pass unmodified
- [x] 4.3 Propose a unit test asserting `investigate()` actually calls the
      injected `fetch_logs` (public seam only - the real client-server path
      is covered by 3.4's integration test and the existing e2e)

## 5. e2e wiring

- [x] 5.1 Add `_start_read_mcp`/`_wait_for_read_mcp`/`_stop_read_mcp` helpers
      to `noxfile.py`, mirroring `_start_argus_web`/`_wait_for_argus_web`/
      `_stop_argus_web`
- [x] 5.2 Start/stop the read server alongside `argus_web` in the `e2e`
      session's `try`/`finally`
- [x] 5.3 Run `nox -s e2e` and confirm
      `test_investigator_diagnoses_a_feature_flag_toggle_as_the_cause` still
      passes, now routed through `argus-read-mcp`

## 6. Verification

- [x] 6.1 `nox -s lint`
- [x] 6.2 `nox -s typecheck`
- [x] 6.3 `nox -s test_module(module='read_mcp_server')` and
      `test_module(module='read_mcp_client')`
- [x] 6.4 `nox -s test_all`
- [x] 6.5 `nox -s guard_e2e_boundary`
- [x] 6.6 `nox -s e2e`
