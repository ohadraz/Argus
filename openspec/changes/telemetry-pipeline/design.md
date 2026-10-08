## Context

Argus runs as several host processes: the worker, both MCP servers, `argus_web`, the Slack relay, and the index loop. Compose brings up only postgres, Qdrant and Prometheus. Logging today is `logging.basicConfig(level=INFO)` to the console in `main`. Every model call and tool call is already recorded to `replay_log` with request, response and `latency_ms`. That table is for replay and eval, not for a person debugging.

The kernel (`argus_core`) depends on nothing in the workspace and is reached through its front doors. Two parts of it are natural points to instrument:
- the `LLMClient` Protocol, already wrapped by a recording decorator (`RecordedLLMClient`, built in `llm/building.py`);
- `McpClient.call`, which every tool call passes through.

## Goals / Non-Goals

**Goals:**
- One instrumentation API, OTel's, used everywhere. Which exporters run is configuration alone.
- Files on disk always, in a format any OTLP backend ingests.
- A walk readable as one trace tree, with GenAI attributes on LLM spans.
- Ready for a backend: setting an endpoint (general) or three Langfuse values is the whole switch.

**Non-Goals:**
- New log lines, or changing the levels of existing ones. That is the second change.
- Uploading old files to a backend.
- Rotating or pruning the telemetry directory.
- Running any backend in compose.

## Decisions

**1. The API in the kernel, the SDK in a new module `argus_telemetry`.**
`argus_core` gains `opentelemetry-api` only. The API is a no-op until an SDK is installed, which is what keeps every unit test and every un-started process unaffected.
- `argus_telemetry` owns the SDK, the providers, the file exporters and the backend wiring. It exposes one function, `start_telemetry(settings: TelemetrySettings, service: str) -> Telemetry`, a handle whose `close()` flushes. Each process's `main` calls it.
- Alternative considered: putting the SDK in `argus_core`. Rejected because every module would then carry the SDK and the exporters, and the kernel would grow a process-wide side effect.

**2. Settings are a `TelemetrySettings` slice in `argus_core.config`.** Fields:
- `telemetry_directory`, default `telemetry`;
- `otel_exporter_otlp_endpoint` and `otel_exporter_otlp_headers`, both default empty;
- `langfuse_base_url`, `langfuse_public_key` and `langfuse_secret_key`, all default empty.

The general backend uses the standard OTel variable names, because those are the names anyone configuring a backend already knows. Langfuse uses its own documented names (`LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`), per the vendor-jargon rule.

Every exporter is constructed with explicit arguments taken from `Settings`. None of them reads the environment, so the Langfuse exporter cannot pick up the general backend's headers or endpoint. (Pydantic reads `.env` into `Settings` without exporting it to `os.environ`, so the SDK's own env reading would see nothing from `.env` anyway.)

**3. The file exporters are OTel's own: `opentelemetry-exporter-otlp-json-file`.**
- The package is published from the `opentelemetry-python` repository: 0.66b1, beta, paired with SDK 1.45.1.
- It implements the OTLP file-exporter spec with three classes: `FileSpanExporter`, `FileMetricExporter` and `FileLogExporter`. Each appends compact OTLP JSON lines, one per batch, to a path opened in UTF-8 append mode.
- Its encoder (`opentelemetry-exporter-otlp-json-common`) produces the OTLP/JSON mapping, hex ids included, so that is the vendor's to get right rather than ours.
- A write failure is logged and reported as a failed export, never raised. That already satisfies "telemetry never changes the work" at the sink.
- Alternatives considered:
  - our own exporters over the protobuf encoders: rejected now that the official one exists;
  - `ConsoleSpanExporter(out=file)`: rejected because its JSON is the SDK's own, not OTLP, so no backend can ingest it.

**4. One run directory per process: `<telemetry_directory>/<service>/<UTC start>-<pid>/`.**
- Two processes appending to one file can interleave a large batch. A prompt-carrying span batch is far larger than any atomic append, so files are never shared.
- One directory per run is also the unit a person reading files wants: "the worker's run that just failed".
- The start is read from the wall clock, not `utc_now`. The SDK stamps every span from the wall, and a stack on simulated time would otherwise name a directory for a moment its own contents never mention.

**5. Batch processors and periodic readers, flushed on close.**
- Spans and logs use `BatchSpanProcessor` and `BatchLogRecordProcessor`. Metrics use a `PeriodicExportingMetricReader`, one per exporter.
- Default intervals give the "within seconds" a backend sees.
- `main` closes the handle as it ends (`contextlib.closing`), so a process that returns flushes what it holds.
- A stop signal (SIGTERM, and CTRL_BREAK on Windows) ends a process past every `finally`. `start_telemetry` therefore installs a handler that closes the handle, then restores the default and re-raises the signal. Nothing else learns the process was stopped: a walk interrupted mid-step is left for its lease to expire, as before. Rejected: raising `SystemExit` from the handler, which would unwind an in-flight walk through code that never expected it.
- `argus_web` gets a `main` of its own (`argus_web.serving`) rather than starting telemetry in its lifespan, because every `TestClient` runs the lifespan.

**6. The LLM span is a decorator, `TracedLLMClient`, beside `RecordedLLMClient`.**
- It wraps the `LLMClient` Protocol for the reason the recorder does: any configured client is traced, and the adapter keeps one job.
- `build_llm_client` always wraps with it, and wraps with the recorder too when a `Replay` is given. Tracing is free when telemetry is off, so it is not conditional.
- It is handed the model, provider and room, as the recorder is.
- It also records the two GenAI metrics, since it is the one place that knows both duration and tokens.
- Prompt and response content go in as `gen_ai.input.messages` and `gen_ai.output.messages`, always on. They are JSON strings in the conventions' shape, `{"role": ..., "parts": [{"type": "text", "content": ...}]}`, with `tool_call` and `tool_call_response` parts. The files are for debugging, and debugging without the prompt is guessing.
- Token counts use `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens` and `gen_ai.usage.cache_creation.input_tokens`.

**7. The MCP span lives in `McpClient.call` and `acall`, on the calling thread.**
- The span opens around the future's result, not on the client's loop. The loop runs in its own thread, so a span opened there would have no parent.
- Opening it on the caller's thread is what makes it a child of the agent span.

**7a. Trace context crosses into the MCP servers through the request's `_meta`.**
- The client injects the active context, as W3C `traceparent` and `tracestate`, into `call_tool(..., meta=...)`. The installed MCP SDK (1.29.0) accepts `meta`.
- Each server extracts it at the start of a tool handler and opens a SERVER span `tools/call <tool>` under it. The tool's work, and every log line it writes, then carry the walk's trace id, even though they land in the server's own files.
- The context goes in `_meta`, not in HTTP headers, because the session is held open and shared: the headers are fixed when the session is opened, while `_meta` travels with each call.
- Extracting it is one shared helper in `argus_core.mcp_transport`, beside the injection, so both halves of one convention live in one place.
- A request with no `_meta` context, such as one from a client that doesn't send it, starts a trace of its own rather than failing.
- This is the convention OTel's MCP semantic conventions and MCP's SEP-414 both prescribe, and the span names (`tools/call <tool>`) follow the same conventions.

**8. Walk and agent spans in the orchestrator.**
- The walk span opens where a run is walked (`run_incident`).
- The agent spans open at each graph node that delegates to an agent. The graph's nodes are the place that knows which agent is running, and a node wrapper keeps the agents themselves free of tracing code.

**9. Logs: OTel's `LoggingHandler`, from `opentelemetry-instrumentation-logging`, on the root logger beside the console handler.**
- The SDK's own `LoggingHandler` is deprecated in favour of this one (1.45.1 warns on construction).
- `start_telemetry` adds it, and `basicConfig` stays.
- The handler takes the active span's context, which is what gives each record its trace id.

**10. `latency_ms` leaves the replay log entirely.**
- It goes from the column, `ReplayEntry`, `Replay.record`, and the three call sites that compute it (`recorded_client.py`, `dispatch.py`, `investigation.py`).
- Migration `001` is edited in place, since it is the whole chain and `nox -s schema` drops first.
- The clocks injected only to compute latency are removed along with it, where nothing else reads them.

## Risks / Trade-offs

- **The telemetry directory grows without bound, and prompt content makes it grow fast.** Mitigation: it is gitignored and per-run, so deleting old runs is one `rm`. Rotation is a non-goal until it is a problem.
- **Prompts and responses go to disk in plain text, and to any configured backend.** They can contain whatever the Target Service logged. Mitigation: the files are local and gitignored. Sending them to a backend is opt-in by configuring one. The setting comments say plainly that content is sent.
- **The GenAI semantic conventions are still marked "development" and have renamed attributes before** (`gen_ai.system` → `gen_ai.provider.name`, message events → message attributes). Mitigation: the attribute names are `Final` constants in one module, named per the wire-vocabulary rule, so a rename is one edit.
- **The Python logs signal is still experimental.** The SDK is `opentelemetry.sdk._logs`, and the file exporter's log class lives in `..._log_exporter`, both underscore modules (checked against 1.45.1). That brushes against the repo's private-name rule, which governs Argus's own names, not a vendor's experimental package. Both imports are confined to `argus_telemetry` and commented as the vendor's experimental surface.
- **The file exporter is beta and pinned in lockstep with the SDK** (`0.66b1` requires `opentelemetry-sdk~=1.45.1`). An SDK upgrade waits for the matching exporter release. uv resolves that pairing; nothing is pinned by hand.
- **Exporters log their own failures through `logging`, which the log bridge exports.** A failing log export could then feed itself. Mitigation: the OTel handler does not export records from the `opentelemetry` logger tree.
- **Spans opened on the wrong thread lose their parent.** Mitigation: decision 7, plus a test asserting the tool span's parent.
- **Removing `latency_ms` breaks the suites that pass or assert it.** Those files are off-limits to Claude. Mitigation: the edits are proposed in chat as whole files, first, before the implementation that makes them pass.

## Migration Plan

1. Run `nox -s schema` after pulling. It drops and re-applies `001`, so local data in `replay_log` is lost, as with any schema change here.
2. Rollback is reverting the commit and re-running `nox -s schema`.
3. Nothing has to be configured: with no backend set, the only visible change is a `telemetry/` directory.

## Open Questions

- None open. Checked on 2026-10-08:
  - OTel Python 1.45.1 ships the OTLP JSON file exporter (decision 3), and its logs SDK is still `_logs`.
  - The GenAI attribute names are as in decision 6. The conventions now live in their own `semantic-conventions-genai` repository, all still "Development".
  - Langfuse takes traces at `/api/public/otel/v1/traces`, with Basic auth of `public_key:secret_key`, over OTLP/HTTP (protobuf or JSON, not gRPC).
