## Why

Argus has almost no observability of its own: 19 log calls across 10 files, plain-text `logging.basicConfig`, and no traces or metrics. What a walk did, which agent called what, how long each model call took and what it cost can only be reconstructed by querying `replay_log` by hand. The project needs to be "ready" for a real backend without running one now, and the data has to land somewhere a person can read it while debugging.

## What Changes

- Argus is instrumented with the OpenTelemetry API, and only the API: traces, metrics and logs.
- Every Argus process (the worker, both MCP servers, `argus_web`, the Slack relay and the index loop) writes all three signals as OTLP JSON lines to a gitignored directory on disk. This happens always, whether a backend is configured or not. The directory is configurable and defaults to `telemetry/`.
- There are two optional backends, and each is off while its settings are empty:
  - a general OTLP backend, which gets all three signals;
  - Langfuse, which gets traces only.
  Both may be configured at once. Traces then reach both, on purpose, so that each backend is complete on its own. A configured backend receives data within seconds, not after the fact.
- The trace shape is one trace per incident walk, with a span per agent, per MCP tool call and per LLM call. LLM spans follow OTel's GenAI semantic conventions: model, input, output and cache tokens, finish reason, and the full prompt and response content.
- Trace context is sent with every MCP tool call, in the request's `_meta`. The servers continue it, so a tool's server-side spans and log lines carry the walk's trace id even though they land in the server's own files.
- Metrics cover GenAI call duration and token usage, MCP tool call duration, and incident walk count and duration by outcome.
- Stdlib `logging` is bridged to OTel logs, so each existing log line carries the trace and span it was written in. No new log lines are added here; that is a separate, later change.
- The new settings are added to `.env.example` and to the local `.env`, commented out and documented.
- **BREAKING** (schema): `replay_log.latency_ms` is removed, along with `ReplayEntry.latency_ms` and the `latency_ms` parameter of `Replay.record`. Latency is telemetry, not something a replay needs, and the LLM and MCP spans now carry it. Revision `001` is edited in place, since it is still the whole chain.

## Capabilities

### New Capabilities
- `telemetry-pipeline`: how Argus emits traces, metrics and logs. Covers the always-on file sink and its format and location, the two optional backends and what each receives, the span hierarchy of a walk, the GenAI attributes on an LLM span, the metric set, and the log bridge with trace correlation.

### Modified Capabilities
<!-- None: no existing openspec spec covers replay_log's columns; the change to it is recorded in docs/spec-and-architecture.md §11.1. -->

## Impact

- **New module** `modules/argus_telemetry/`: the OTel SDK setup, and the wiring of OTel's OTLP JSON-lines file exporters and the backends. It depends on `argus_core` and joins `[tool.importlinter] root_packages`.
- **`argus_core`**:
  - gains `opentelemetry-api` (the API only, no SDK) and a `TelemetrySettings` slice;
  - a traced `LLMClient` decorator sits beside `RecordedLLMClient`;
  - `McpClient` gets a span per tool call;
  - `replay.py` loses `latency_ms`, and so do migration `001` and `recorded_client.py`.
- **Each process's `main`** (`orchestrator.worker`, `read_mcp_server.server`, `write_mcp_server.server`, `argus_web`, `agent_communicator.watching`, `code_index.catching_up`) starts telemetry once.
- **Agents**: `agent_investigator` (the `dispatch.py` and `investigation.py` record calls) drops `latency_ms`. The orchestrator opens the walk span and the agent spans.
- **Tests under `tests/` and each module's suite** that pass or assert `latency_ms` need edits. Those files are off-limits to Claude and are proposed in chat.
- **New dependencies**: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` and `opentelemetry-exporter-otlp-json-file` (beta).
- **Docs and config**: `docs/spec-and-architecture.md` (§11.1 `REPLAY_LOG`, plus observability), `.env.example`, `.gitignore`.
