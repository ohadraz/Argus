## RENAMED Requirements

### Requirement: A walk is one trace
FROM: A walk is one trace
TO: An incident is one trace

## MODIFIED Requirements

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

### Requirement: Logs carry their trace
Records logged through stdlib `logging` SHALL be exported as OTel log records, with severity, logger name, message and the attributes stamped from the baggage (see `process-logging`). A record logged inside a span SHALL carry that span's trace id and span id. The console handler SHALL be installed by `start_telemetry` beside the OTel handler.

#### Scenario: A log line inside a walk
- **WHEN** code running inside a walk logs at INFO
- **THEN** the log record in `logs.jsonl` carries the walk's trace id and `argus.incident.id`
