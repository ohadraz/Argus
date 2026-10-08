## 1. Verify vendor facts (free, before any code)

- [x] 1.1 Check the installed OTel `LoggingHandler` exports dotted, non-reserved record attributes under their own names, and that the default global propagator is `tracecontext,baggage`.
- [x] 1.2 Check that `FastMCP.streamable_http_app()` carries the session manager's lifespan, so `uvicorn.run(app, log_config=None)` serves what `run(transport="streamable-http")` served.
- [x] 1.3 Check that `uvicorn.run(..., log_config=None)` leaves `uvicorn` and `uvicorn.error` propagating to the root. Update design.md wherever any of these was wrong.

## 2. Settings and names

- [x] 2.1 Propose a failing test that `TelemetrySettings.log_level` defaults to `INFO` and narrows from `Settings`.
- [x] 2.2 Add `log_level` to `Settings` and `TelemetrySettings`, and add `LOG_LEVEL` to `.env.example` and the local `.env`, commented out.

## 3. Logging configured by `start_telemetry`

- [x] 3.1 Propose failing tests in `argus_telemetry`, against what `telemetry_for` builds:
  - the console handler and its level;
  - the third-party loggers held at WARNING;
  - the stamping filter copying the three baggage keys onto a record, and adding nothing outside any baggage;
  - the redaction filter replacing secret-named attributes;
  - the console line printing every `extra` attribute as `key=value`, the stamped ones first;
  - the console written through a queue, its listener stopped by `close()`;
  - a stamped record reaching `logs.jsonl` with the keys as attributes.
- [x] 3.2 Implement the console handler, the queue, the levels, both filters and the formatter in `argus_telemetry` (`records.py`, `levels.py`, `wiring.py`), add `ARGUS_RUN_ID` to `argus_core.telemetry`, and install them in `start_telemetry`.
- [x] 3.3 Propose failing tests for `Telemetry` as a context manager:
  - INFO `"service started"` on entry;
  - INFO `"service stopped"` on a normal exit, `SystemExit` and `KeyboardInterrupt`;
  - CRITICAL `"service died"` with `exc_info` on any other exception, which still propagates;
  - `close()` on every exit;
  - `"service stopped"` on the signal path.
- [x] 3.4 Implement it, and switch every `main` from `closing(start_telemetry(...))` to `start_telemetry(...)`.
- [x] 3.5 Delete the `basicConfig` calls in `orchestrator.worker`, `agent_communicator.watching` and `code_index.catching_up`. `schema` starts no telemetry (the kernel depends on nothing), so it keeps its own and says why in its docstring. The worker's "waiting for runs" line is left for 6.1.

## 4. Servers' loggers reach the root

- [x] 4.1 Propose a failing test for `TracedFastMCP.serve` in `argus_core`'s `mcp_transport` suite: it serves the app with uvicorn's logging config switched off.
- [x] 4.2 Implement `TracedFastMCP.serve`, and switch both MCP servers' `main` to it.
- [x] 4.3 Pass `log_config=None` in `argus_web/serving.py`.
- [x] 4.4 Run both MCP servers' component suites and the `argus_web` suite, and get them green.

## 5. An incident is one trace

- [x] 5.1 Add `trace_context JSONB` to `incident` in revision `001`. The module suites bring up their own postgres and apply it.
- [x] 5.2 Propose failing tests in `argus_incidents`: `start_incident` stores the carrier it is given, an alert joined to an open incident leaves the stored carrier unchanged, and the incident record reads it back. And `inside_the_incidents_trace`: the work is a child of the stored context, an empty one starts a trace of its own, the span names the incident, the incident is in the baggage during the work and not after, and a failure is said on the span and raised on.
- [x] 5.3 Implement them.
- [x] 5.4 Propose failing tests in `argus_web`, using an in-memory span exporter handed in through a FastAPI dependency:
  - intake opens a `receive alert` SERVER span carrying the incident id, and the incident keeps that span's context;
  - a resolutions-only webhook ends the span with no incident id;
  - `withdraw` works inside the incident's trace.
- [x] 5.5 Implement the two spans in `argus_web`.
- [x] 5.6 Propose failing tests in `orchestrator`'s worker: each claimed run (walk and unwind alike) is a `run` span inside the incident's trace, naming the incident and the run, and the walk runs with both ids in the baggage. `run_incident` and `unwind_incident` are unchanged: they run inside the run's span.
- [x] 5.7 Implement them.
- [x] 5.8 Propose a failing test in `argus_core`'s `mcp_transport` suite that baggage crosses a tool call into the server's context.
- [x] 5.9 Make it pass, or record that it already does.

## 6. Log lines, module by module

The sites are listed in `log-sites.md`. For each module below, re-read its sites, then confirm or correct each one against the level policy. Propose one failing `caplog` test per line at INFO and above, one at a time. Implement each line as a fixed phrase with its values in `extra` (design D8), and rewrite the module's existing lines to that shape. Run the module's suite.

- [x] 6.1 `orchestrator`: the worker, `entrypoint`, `unwinding` and every `walk/` node.
- [x] 6.2 `agent_investigator`
- [x] 6.3 `agent_mitigation`
- [x] 6.4 `agent_codefix`
- [x] 6.5 `agent_postmortem`
- [x] 6.6 `agent_communicator`
- [x] 6.7 `read_mcp_server`
- [x] 6.8 `write_mcp_server`: every reversible action executed, refused or failed.
- [x] 6.9 `argus_web`: intake, rejection, push verification and withdrawal.
- [x] 6.10 `argus_incidents`
- [x] 6.11 `incident_memory`
- [x] 6.12 `code_index`
- [x] 6.13 `deployment_platform`, `repository_source` and `metrics_source`
- [x] 6.14 `oncall_source` and `revenue_source`
- [x] 6.15 `argus_core`: `mcp_transport`, `events`, `replay` and `schema`.

## 7. Docs

- [x] 7.1 Add the level policy, the stamped attributes and the intake-rooted trace to §19.1 of `docs/spec-and-architecture.md`, per the `spec-doc-style` skill.

## 8. Verification

- [x] 8.1 Run `lint`, `typecheck`, `guard_layering` and `test_all`, and get them green.
- [x] 8.2 Run `e2e_replay(mode='both')` in the background. Then check one incident's run directories: the `argus-web` `traces.jsonl` holds the intake span, and the worker's walk span shares its trace id; `argus-web`'s `logs.jsonl` is not empty; a read MCP server record carries `argus.incident.id`.
