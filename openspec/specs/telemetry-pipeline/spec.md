# telemetry-pipeline Specification

## Purpose
TBD - created by archiving change telemetry-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Every signal is written to disk, always
Every Argus process SHALL write its traces, metrics and logs to files under a configured telemetry directory. Each signal SHALL go to its own file, as OTLP JSON lines: one export batch per line, encoded per the OTLP/JSON mapping, with trace and span ids in hex. This SHALL happen whether or not any backend is configured. Each process run SHALL write into a directory of its own, named for the service and the run, so that two processes never append to the same file. The run is named for the real clock's start, whatever the stack's clock reads, because every time inside the files is the real clock's.

#### Scenario: No backend configured
- **WHEN** a process starts with neither backend configured and then emits a span, a metric point and a log record
- **THEN** `traces.jsonl`, `metrics.jsonl` and `logs.jsonl` exist in that process's run directory, and each holds a line that parses as OTLP JSON

#### Scenario: The directory is configurable
- **WHEN** `TELEMETRY_DIRECTORY` names a directory
- **THEN** the run directories are created under it rather than under the default `telemetry/`

#### Scenario: Two processes do not share a file
- **WHEN** two processes run at the same time
- **THEN** each writes to a run directory of its own

#### Scenario: A stack on a simulated clock
- **WHEN** a process starts in a stack whose clock runs ahead of the real one
- **THEN** its run directory is named for the real time it started

### Requirement: A stopped process flushes what it holds
A process SHALL flush its batched telemetry when it returns from `main` and when it receives a stop signal: SIGTERM, or CTRL_BREAK on Windows. After flushing on a signal, the process SHALL end as the signal's default would have ended it, and nothing else in the process SHALL observe that it was stopped.

#### Scenario: Stopped by its signal
- **WHEN** a process that has ended a span is sent its stop signal
- **THEN** that span is in its `traces.jsonl` once the process has exited

### Requirement: A general OTLP backend receives every signal when configured
When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the system SHALL export traces, metrics and logs to it over OTLP/HTTP, in addition to the files. It SHALL send any headers configured in `OTEL_EXPORTER_OTLP_HEADERS`. When the endpoint is empty, nothing SHALL be sent anywhere but the files.

#### Scenario: Endpoint empty
- **WHEN** `OTEL_EXPORTER_OTLP_ENDPOINT` is empty
- **THEN** no OTLP network exporter is installed for any signal

#### Scenario: Endpoint set
- **WHEN** `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- **THEN** an OTLP/HTTP exporter is installed for traces, metrics and logs, alongside the file exporters

### Requirement: Langfuse receives traces when configured
When `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are all set, the system SHALL export traces to Langfuse's OTLP traces endpoint, `<base>/api/public/otel/v1/traces`, authenticated with HTTP Basic auth from the two keys, in addition to the files. Metrics and logs SHALL NOT be sent to Langfuse. When any of the three is empty, nothing SHALL be sent to Langfuse.

#### Scenario: Langfuse configured
- **WHEN** all three Langfuse settings are set
- **THEN** an OTLP/HTTP span exporter is installed whose endpoint is the base URL followed by `/api/public/otel/v1/traces`, and whose authorization header is Basic auth of `public_key:secret_key`

#### Scenario: Langfuse partly configured
- **WHEN** only some of the three Langfuse settings are set
- **THEN** no Langfuse exporter is installed

#### Scenario: Both backends configured
- **WHEN** both the general backend and Langfuse are configured
- **THEN** every span is exported to both, and to the file

### Requirement: Telemetry never changes the work
A failure to export, to write a file, or to configure telemetry SHALL NOT fail an incident walk, a tool call or a process's startup. Where telemetry is not started at all, as in a unit test, the instrumentation SHALL do nothing.

#### Scenario: Unwritable directory
- **WHEN** the telemetry directory cannot be created or written
- **THEN** the process starts and works, and logs a warning that telemetry is not being written

#### Scenario: Instrumented code with telemetry not started
- **WHEN** an instrumented call runs in a process that never started telemetry
- **THEN** the call behaves exactly as it would uninstrumented

### Requirement: An incident is one trace
`argus_web` SHALL open a SERVER span for alert intake. When intake opens an incident, the span SHALL carry `argus.incident.id`, and its context SHALL be stored with the incident. Every walk of that incident, every unwind of it and every withdrawal of it SHALL continue that stored context, so that all of them share the intake's trace id:
- the worker works each claimed run inside a `run` span, carrying `argus.incident.id` and `argus.run.id`, that is a child of the intake span;
- the orchestrator's walk span carries `argus.incident.id`, and is a child of the run span;
- each agent the walk delegates to gets a child span named for the agent and carrying `argus.agent`;
- LLM calls and MCP tool calls made during the walk are descendants of the agent span that made them.

An incident with no stored context SHALL be walked under a trace of its own.

#### Scenario: A walk's spans share a trace
- **WHEN** a walk runs an investigation that calls a model and a tool
- **THEN** the walk span, the investigator span, the LLM span and the tool span all have one trace id, and the LLM and tool spans are descendants of the investigator span

#### Scenario: The trace starts at the alert
- **WHEN** an alert opens an incident and a worker then walks it
- **THEN** the run span's parent is the intake span, and the walk span is the run span's child

#### Scenario: A walk taken up again
- **WHEN** a run's lease expires and another worker walks the same incident
- **THEN** both run spans, and the walk spans below them, have the intake span's trace id

#### Scenario: An alert that joins an open incident
- **WHEN** a rule fires again for a service whose incident from that rule is still open
- **THEN** the intake span carries that incident's id, and the context stored with the incident is unchanged

#### Scenario: An alert that opens nothing
- **WHEN** a webhook reports only resolutions
- **THEN** the intake span ends without `argus.incident.id`, and nothing is stored

### Requirement: An LLM call is a GenAI span
Each model call SHALL produce a span named `chat <model>`, of kind CLIENT, carrying the OTel GenAI semantic-convention attributes:
- `gen_ai.operation.name`, `gen_ai.provider.name` and `gen_ai.request.model`;
- `gen_ai.request.max_tokens`;
- the four token counts as reported: input, output, cache read and cache creation;
- `gen_ai.response.finish_reasons`;
- the full input and output messages, as `gen_ai.input.messages` and `gen_ai.output.messages`.

A call that failed SHALL set the span's status to error and carry `error.type`, plus whatever token counts the failure reported.

#### Scenario: A completed call
- **WHEN** a model call completes with a turn
- **THEN** its span carries the model, the turn's token counts, its stop reason as a finish reason, and the transcript and turn as input and output messages

#### Scenario: A failed call
- **WHEN** a model call raises `ModelDidNotAnswer`
- **THEN** its span has error status, `error.type` naming the exception, and the token counts the exception carried

### Requirement: An MCP tool call is a span
Each MCP tool call SHALL produce a CLIENT span named `tools/call <tool>`, carrying the tool name and the server it was made to. A call that failed SHALL set error status and `error.type`.

#### Scenario: A tool reports an error
- **WHEN** a tool call raises `McpToolError`
- **THEN** its span has error status and `error.type` naming the exception's class

### Requirement: A tool call's server-side work joins the caller's trace
The MCP client SHALL send the active trace context with every tool call, in the request's `_meta` as W3C `traceparent`, `tracestate` and `baggage`. Each MCP server SHALL continue that context: the tool's SERVER span, any spans below it, and every log record written while handling the call SHALL carry the caller's trace id and the caller's baggage. A call that arrives without trace context SHALL be handled normally, under a trace of its own.

#### Scenario: A walk's tool call is traced into the server
- **WHEN** an agent span calls a tool on the read MCP server
- **THEN** the server's `tools/call <tool>` span has the caller's trace id, and the client's tool span is its parent

#### Scenario: A server log line inside a tool call
- **WHEN** a tool handler logs while serving a call made from a walk
- **THEN** that log record in the server's `logs.jsonl` carries the walk's trace id

#### Scenario: Baggage crosses with the call
- **WHEN** a tool call is made while the baggage holds `argus.incident.id`
- **THEN** the server's context while handling the call holds the same `argus.incident.id`

#### Scenario: No context sent
- **WHEN** a tool call arrives with no trace context in `_meta`
- **THEN** the tool answers as it always did, and its span starts a new trace

### Requirement: The metric set
The system SHALL record these metrics:
- `gen_ai.client.operation.duration`: a histogram in seconds, by model and agent;
- `gen_ai.client.token.usage`: a histogram, by model, agent and `gen_ai.token.type`;
- `mcp.client.operation.duration`: a histogram in seconds, by tool and outcome;
- `argus.incident.walk.duration`: a histogram in seconds, by outcome;
- `argus.incident.walks`: a counter, by outcome.

#### Scenario: A model call is measured
- **WHEN** a model call completes
- **THEN** one duration point and one token-usage point per token type are recorded, labelled with the model

### Requirement: Logs carry their trace
Records logged through stdlib `logging` SHALL be exported as OTel log records, with severity, logger name, message and the attributes stamped from the baggage (see `process-logging`). A record logged inside a span SHALL carry that span's trace id and span id. The console handler SHALL be installed by `start_telemetry` beside the OTel handler.

#### Scenario: A log line inside a walk
- **WHEN** code running inside a walk logs at INFO
- **THEN** the log record in `logs.jsonl` carries the walk's trace id and `argus.incident.id`

### Requirement: The replay log does not record latency
A `replay_log` row and a `ReplayEntry` SHALL NOT carry a duration. The time a call took is telemetry, and is carried by that call's span.

#### Scenario: Recording an LLM call
- **WHEN** `RecordedLLMClient` records a call
- **THEN** the entry has a request, a response, a target, a call type and a time, and no latency

