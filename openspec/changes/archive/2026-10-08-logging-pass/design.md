## Context

`telemetry-pipeline` bridged stdlib `logging` into OTel, so every record already lands in `logs.jsonl` with its trace id. The logging around that bridge was left as it was:
- three `logging.basicConfig` calls, in the worker, the relay and the index loop;
- servers that rely on uvicorn's own logging, which sets `propagate = False` on `uvicorn` and `uvicorn.access`. Since `start_telemetry` puts a handler on the root before `FastMCP.__init__` runs, the `basicConfig` inside FastMCP's `configure_logging` is also a no-op, so the MCP servers currently have no console handler for Argus's own records;
- 19 log calls, most of which format the incident id into the message.

The walk already puts `argus.agent` in OTel baggage (`orchestrator/walk/tracing.py`), and `mcp_transport` injects the global propagator into `_meta`. The default propagator is `tracecontext,baggage`, so baggage already crosses into the servers.

## Goals / Non-Goals

**Goals:**
- One level policy, applied to every module that makes a decision.
- Every record says whose incident, run and agent it belongs to, without call sites formatting it in.
- `argus-web`'s `logs.jsonl` and `traces.jsonl` stop being empty.
- An incident's trace starts at the alert.

**Non-Goals:**
- A span per HTTP request in `argus_web`. The dashboard polls every two seconds, and those spans would be noise. Only intake and withdrawal get spans.
- Structured JSON on the console. `logs.jsonl` is the structured copy.
- Spans for the relay or the index loop, which are not part of any incident's work.
- Log sampling or rate limiting.
- **Paging on CRITICAL.** Paging is a backend's alert rule over `logs.jsonl` or OTLP, not code in Argus.
- **A TRACE level.** Python has none, and its docs advise against inventing levels. Payload-level detail is span content: the GenAI messages on every model call.

## Decisions

### D1. `start_telemetry` owns logging configuration
`start_telemetry` sets the root level from `TelemetrySettings.log_level` (`LOG_LEVEL`, default `INFO`), installs the console and OTel handlers, and sets the third-party loggers to WARNING.

The console is asynchronous: a `QueueHandler` on the root, drained by a `QueueListener` into a `StreamHandler` on stderr. The listener is stopped by `close()`.

The OTel `LoggingHandler` stays directly on the root, not behind the queue, for two reasons:
- It reads the current span's context when it is called, and on the listener's thread there is none.
- It already only hands the record to a `BatchLogRecordProcessor`, so it does not block.

The stamping and redaction filters (D2, D11) sit on both handlers, so they run on the calling thread, where the baggage is. The handlers are built by `telemetry_for`, so they can be inspected without being installed, as the providers already are. The three `basicConfig` calls are deleted.

The alternative was a separate `configure_logging()` that each `main` calls. That was rejected: every `main` already makes exactly one call, and a second one is a second thing to forget.

The third-party loggers held at WARNING are `httpx`, `httpx2`, `httpcore`, `httpcore2`, `mcp` and `uvicorn.access`, a list in `argus_telemetry`:
- httpx logs every request at INFO.
- `mcp` logs "Processing request of type CallToolRequest" for every call, which the tool span already says.
- `uvicorn.access` would log the dashboard's polls.

### D2. Stamping reads the baggage, through a handler filter
A `logging.Filter` in `argus_telemetry` copies each of `argus.incident.id`, `argus.run.id` and `argus.agent` from `opentelemetry.baggage.get_all()` onto the record as an attribute of that exact dotted name.

The OTel `LoggingHandler` exports every non-reserved record attribute (`_get_attributes` takes `vars(record)` minus `_RESERVED_ATTRS`), so the attributes reach `logs.jsonl` under the same keys the spans use.

The filter is added to both handlers. The console formatter appends every non-reserved attribute of the record as `key=value`, the stamped ones first. A plain `%`-format string cannot do this, because a missing key raises.

The source is baggage rather than a contextvar of Argus's own because baggage already crosses the MCP boundary. A server record gets the walk's incident with no new wiring.

### D3. Who puts what in the baggage
- **`inside_the_incidents_trace`** (in `argus_incidents`) attaches `argus.incident.id` for any work on an incident: a walk, an unwind, a withdrawal.
- **The worker** attaches `argus.run.id` around each claimed run, whether it is a walk or an unwind.
- **`traced()`** keeps attaching `argus.agent`, as now.

One helper rather than one attach per caller, because the baggage is visible only to what runs inside it. A caller's own test can observe a span, and could not observe an attach it made. The helper's test observes both.

The key `ARGUS_RUN_ID` joins `argus_core.telemetry`.

### D4. Intake's context is stored on the incident
`incident` gains `trace_context JSONB`, holding the propagator's carrier: what `propagate.inject` writes, which is `traceparent`, `tracestate` and `baggage`.

The carrier rather than a bare traceparent, because the format is the propagator's to decide, and a stored dict is exactly what `propagate.extract` reads back.

`start_incident` gains a `trace_context: Mapping[str, str]` parameter and writes it in the INSERT. An alert joined to an already-open incident writes nothing: the incident's trace is the first alert's.

Revision `001` is edited in place.

### D5. Continuing the stored context
The worker, for each claimed run, and the withdraw route each read the incident's `trace_context` and do their work inside `inside_the_incidents_trace`. That helper extracts the context and makes it the parent of their span. A run's span wraps the walk and the unwind alike, so `run_incident` and `unwind_incident` need no change: their spans, and every step's below them, hang from the run's.

The walk span becomes a child of the intake span, possibly hours after the intake span ended. OTel and both backends accept a parent that ended long before its child.

The alternative was a span link: a new trace per walk, linked back to intake. That was rejected, because an incident's trace is required to start at the alert. A link would leave intake in a trace of its own.

### D6. Servers run uvicorn with `log_config=None`
`argus_web/serving.py` passes `log_config=None`.

The MCP servers stop calling `FastMCP.run`, whose `uvicorn.Config` cannot be changed from outside. Instead, `TracedFastMCP.serve()` in `argus_core.mcp_transport` runs `uvicorn.run(server.streamable_http_app(), host=server.settings.host, port=server.settings.port, log_config=None)`. The `streamable_http_app()` Starlette app carries the session manager's lifespan, so serving it directly is what `run` did, less the logging config.

### D7. Intake and withdrawal spans are made by hand
`receive_alert` and `withdraw` each open a SERVER span (`receive alert`, `withdraw incident`) with `argus_web`'s own tracer. This needs no `opentelemetry-instrumentation-fastapi`, for the reason in Non-Goals. `argus_web` imports only the OTel API, as `argus_core` does.

### D8. Message shape: a fixed phrase, with values in `extra`
A message is a fixed lowercase phrase naming the event, such as `"service scaled out"`. It is the same for every occurrence, so a backend can group by it.

Values go in `extra` under snake_case keys, such as `extra={"from_replicas": 3, "to_replicas": 6}`, and never into the message. The only dotted keys are the three stamped from the baggage, because those are shared with the spans.

The incident, run and agent are never passed by a call site. The exception is the worker's lease renewal, which runs outside the run's context, so it passes `run_id` itself.

There are no f-strings and no `%` arguments, so nothing is formatted unless a handler formats it. Where an `extra` value is costly to build, the call is guarded with `logger.isEnabledFor`.

Existing messages are rewritten to this shape.

### D10. Telemetry is a context manager that reports the process's life
`Telemetry` gains `__enter__` and `__exit__`, and each `main` writes `with start_telemetry(...)` in place of `with closing(start_telemetry(...))`:
- `__enter__` logs INFO `"service started"`.
- `__exit__` logs INFO `"service stopped"` on a normal exit, `SystemExit` or `KeyboardInterrupt`.
- On any other exception, `__exit__` logs CRITICAL `"service died"` with `exc_info` and does not suppress the exception.
- Every exit calls `close()`.

The signal path in `_closed_when_stopped` logs `"service stopped"` before it flushes.

This puts every CRITICAL in one place. A `main` that cannot load its settings, or finds no schema, raises, and the raise becomes the CRITICAL. Settings that fail before telemetry starts never reach this: pydantic's error on stderr is all there is, and there is no handler yet to log to.

### D11. Redaction by attribute name
A filter on both handlers replaces the value of any attribute whose name contains `token`, `secret`, `password`, `api_key` or `authorization` (case-insensitive) with `"[redacted]"`. It runs before stamping.

Message text is not scanned. Since D8 keeps values out of messages, an attribute is the only way a value reaches a log. Free-text scanning would be a guess at what a secret looks like.

### D9. How a line is tested
Every record at INFO and above has a unit test in its module's suite:
- the test drives the decision through the function that makes it;
- it asserts with pytest's `caplog` that exactly one record exists from that logger, at that level, with that message and those `extra` attributes.

Stamping and configuration are tested once, in `argus_telemetry`, against handlers built by `telemetry_for`, and are never re-asserted per line. The intake-to-walk trace is tested with an in-memory span exporter in `argus_web`'s suite (intake stores a carrier) and the orchestrator's (a walk given a carrier is its child).

All of these tests are proposed in chat, whole files, one at a time.

## Risks / Trade-offs

- **Volume of tests to paste.** Roughly one test per line added, across about a dozen modules. Mitigation: the tasks go module by module, so each batch is one suite.
- **Baggage is sent on every MCP call.** It holds three short ids and goes only to Argus's own servers. No outbound HTTP client is instrumented, so baggage never reaches a vendor.
- **A trace hours long.** A long walk makes the intake span's trace span hours. Langfuse and OTLP backends accept this. It is the shape that was asked for.
- **FastMCP's `run` may grow behaviour that serving the app directly misses.** The component tests of both servers already go through the real transport, so a missed lifespan fails them.

## Migration Plan

- Run `nox -s schema`, which drops and re-applies `001`.
- `.env.example` gains `LOG_LEVEL`.
- Nothing else migrates.

## Open Questions

None.
