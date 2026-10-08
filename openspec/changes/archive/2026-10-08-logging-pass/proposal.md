## Why

`telemetry-pipeline` gave every process a log file with trace ids in it. What gets written there is still the 19 lines that came before it. A walk that went wrong cannot be read from its logs: the choices it made are missing, and so are the reasons for them. `argus-web` writes nothing at all. Its uvicorn loggers never reach the root logger, and alert intake has no span, so an incident's trace starts at a worker's claim and not at the alert that opened it.

## What Changes

- **A level policy, applied across the code:**
  - CRITICAL: the process cannot continue.
  - ERROR: an operation failed and a person needs to act.
  - WARNING: unexpected, but recovered or degraded gracefully.
  - INFO: a lifecycle milestone or a business event, never inside a per-item loop.
  - DEBUG: diagnostic context, including branch decisions.
  - There is no TRACE level. Payloads stay in spans.
  - Existing lines are re-levelled to the policy, and the missing lines are added.
- **Key-value context:** a message is a fixed phrase, and its values go in `extra`.
- **Secrets never reach a log:** secret-named attributes are redacted by a filter.
- **A process logs that it started and stopped**, and logs CRITICAL with the stack trace when it dies. One context manager does this for every process.
- **The console is written off the calling thread**, through a queue.
- **Every line at INFO and above is test-driven:** each gets a failing `caplog` assertion first, in its module's own unit test.
- **Logging is configured once, by `start_telemetry`:**
  - It installs a console handler and sets the root level from a new `LOG_LEVEL` setting, which defaults to INFO.
  - It holds third-party chatter at WARNING: httpx, httpcore, `mcp`, and `uvicorn.access`, which the dashboard's two-second polls would otherwise flood.
  - The three `logging.basicConfig` calls go.
- **Every log record is stamped** with `argus.incident.id`, `argus.run.id` and `argus.agent` wherever the context knows them. These are read from OTel baggage, so the stamp crosses into the MCP servers with the trace context, and no call site formats an incident id into its message any more.
- **The servers' own loggers reach the root logger:**
  - `argus_web` and both MCP servers run uvicorn with `log_config=None`.
  - The MCP servers run their app through one helper in `argus_core.mcp_transport`, not through `FastMCP.run`, whose uvicorn config cannot be changed from outside.
- **An incident is one trace, starting at the alert:**
  - `argus_web` opens a span for alert intake.
  - The intake span's context is stored on the incident row.
  - Every walk, unwind and withdrawal of that incident continues that context.
- **BREAKING** (schema): `incident` gains a `trace_context JSONB` column. Revision `001` is edited in place, since it is still the whole chain.

## Capabilities

### New Capabilities
- `process-logging`: what Argus logs and at what level. Covers the level policy, the `LOG_LEVEL` setting, the console handler, the third-party loggers held at WARNING, the attributes stamped onto each record, and the servers' loggers reaching the root logger.

### Modified Capabilities
- `telemetry-pipeline`:
  - "A walk is one trace" becomes "An incident is one trace", rooted at an intake span in `argus_web` and continued by every walk.
  - A tool call's `_meta` carries baggage as well as `traceparent` and `tracestate`.
  - "Logs carry their trace" adds the stamped attributes, and the console is now configured by `start_telemetry`.

## Impact

- **`argus_telemetry`:** `start_telemetry` configures logging, adding a console handler, the levels and the stamping filter.
- **`argus_core`:**
  - `TelemetrySettings` gains `log_level`.
  - `argus_core.telemetry` gains `ARGUS_RUN_ID`.
  - `mcp_transport` gains the uvicorn-serving helper.
  - Migration `001` gains `incident.trace_context`.
- **`argus_incidents`:** `start_incident` stores the intake context, and the incident record exposes it.
- **`orchestrator`:**
  - `run_incident` and `unwind_incident` continue the stored context.
  - The worker puts the run id in the baggage.
- **`argus_web`:** an intake span and a withdrawal span, `log_config=None`, and log lines for intake, rejection and withdrawal.
- **Every module with decisions to log:** orchestrator, the agents, both MCP servers, `argus_incidents`, `incident_memory`, `code_index`, `agent_communicator`, `deployment_platform`, `repository_source` and `metrics_source`.
- **Tests:** a failing test per INFO+ line, under each module's own suite. All of them are proposed in chat, since test files are off-limits to Claude.
- **Docs and config:** `docs/spec-and-architecture.md` §19.1, and `.env.example` gains `LOG_LEVEL`.
