## 1. Verify vendor facts (free, before any code)

- [x] 1.1 Check the current OTel Python release: whether it ships an OTLP JSON file exporter, whether the logs SDK is still `opentelemetry.sdk._logs`, and the current GenAI attribute names for cache tokens and input/output messages. Update design.md where it was wrong.
- [x] 1.2 Check Langfuse's OTLP endpoint docs: the path, the auth header, and whether OTLP/HTTP protobuf is accepted.

## 2. Replay log loses latency

- [x] 2.1 Propose, as whole files in chat, the test edits that drop `latency_ms` from `argus_core_test/test_replay.py`, `argus_core_test/framework/replay.py`, `argus_core_test/llm/test_conversing.py` and `argus_incidents_test/repository/test_replay.py`. The user applies them and they fail.
- [x] 2.2 Remove `latency_ms` from migration `001`, `ReplayEntry`, `Replay.record`, the `argus_incidents` replay repository, `recorded_client.py`, `agent_investigator/tools/dispatch.py` and `agent_investigator/investigation.py`. Remove clocks that existed only for it.
- [x] 2.3 Remove `latency_ms` from `REPLAY_LOG` in `docs/spec-and-architecture.md` §11.1.
- [x] 2.4 Run `nox -s schema`, the affected `test_module` sessions, `typecheck` and `lint`, and get them green.

## 3. Settings

- [x] 3.1 Propose a failing test for `TelemetrySettings`: its defaults (`telemetry`, every backend value empty) and that it narrows from `Settings`.
- [x] 3.2 Add the six fields to `Settings` and the `TelemetrySettings` slice.
- [x] 3.3 Add a commented "Telemetry" section to `.env.example`: the directory, the general backend (standard OTel names) and Langfuse (its three names). Say in it that prompt content is sent to any configured backend. Mirror the section into the local `.env`, commented out.
- [x] 3.4 Add `telemetry/` to `.gitignore`.

## 4. The `argus_telemetry` module

- [x] 4.1 Scaffold `modules/argus_telemetry/` per the `new-module` skill, with deps `argus_core`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` and `opentelemetry-exporter-otlp-json-file`. Add it to importlinter `root_packages` and its layer contract, then `uv sync --all-packages`.
- [x] 4.2 Propose failing tests for the wiring:
  - the run directory naming;
  - one OTLP JSON file per signal, written by OTel's file exporters;
  - no network exporter when the endpoint is empty;
  - a general exporter for all three signals when it is set;
  - a Langfuse span exporter only when all three Langfuse values are set, with the endpoint path and Basic auth;
  - an unwritable directory warning without raising.
- [x] 4.3 Implement `start_telemetry(settings, service) -> Telemetry`, with `close()` flushing every provider.
- [x] 4.4 Propose a failing test that a log record emitted inside a span lands in `logs.jsonl` with that span's trace id. Implement the `LoggingHandler` installation.

## 5. Instrumentation in the kernel

- [x] 5.1 Add `opentelemetry-api` to `argus_core`. Put the GenAI and MCP attribute names in one module as `Final` constants.
- [x] 5.2 Propose failing tests for `TracedLLMClient`, using an in-memory SDK exporter injected in the test: span name and kind, the GenAI attributes, input and output messages, the token counts, the finish reason, error status with `error.type` and counts on `ModelDidNotAnswer`, and the duration and token-usage metric points.
- [x] 5.3 Implement `TracedLLMClient`, and have `build_llm_client` always wrap with it.
- [x] 5.4 Propose failing tests for the `McpClient` tool span: its name, attributes, error status on `McpToolError`, and its parent being the caller's active span. Record `mcp.client.operation.duration`.
- [x] 5.5 Implement the span in `call` and `acall`, opened on the calling thread.

- [x] 5.6 Propose failing tests for trace-context propagation: the client puts `traceparent` into `call_tool`'s `meta`; the server-side helper continues it, so the server span shares the caller's trace id and has the client span as its parent; a call with no context gets a fresh trace.
- [x] 5.7 Implement injection in `McpClient` and the extraction helper in `argus_core.mcp_transport`. Apply it at the start of every tool handler in `read_mcp_server` and `write_mcp_server`, through one shared wrapper rather than per tool.
## 6. Walk and agent spans

- [x] 6.1 Propose a failing test that a walk produces one trace: a walk span carrying `argus.incident.id`, agent spans carrying `argus.agent`, and LLM and tool spans under the agent that made them.
- [x] 6.2 Implement the walk span in `run_incident` and the agent spans at the graph's agent nodes. Record `argus.incident.walks` and `argus.incident.walk.duration` by outcome.

## 7. Start it in every process

- [x] 7.1 Call `start_telemetry` (and `close()` in `finally`) in the `main` of the worker, both MCP servers, `argus_web`, the Slack relay and the index loop, each with its service name.
- [x] 7.2 Run `nox -s guard_layering`, `typecheck`, `lint` and `test_all`, and get them green.
- [x] 7.3 Run `e2e_replay(mode='both')` in the background. Confirm it passes and that `telemetry/` holds a worker run directory whose `traces.jsonl` shows a walk tree with LLM spans.

## 8. Spec doc

- [x] 8.1 Add an observability subsection to `docs/spec-and-architecture.md`, per the `spec-doc-style` skill. It covers the signals, the file sink, the two backends, the span hierarchy, and trace context crossing into the MCP servers through `_meta`, so that one walk is one trace across every process.
