## ADDED Requirements

### Requirement: Levels mean one thing everywhere
Every log record Argus writes SHALL be at the level its content calls for:
- **CRITICAL**: the process cannot continue. Examples are a mandatory setting missing at startup, the schema absent, or an exception escaping `main`. Logged with the stack trace, before the process ends.
- **ERROR**: an operation failed, the process stays up for other work, and a person needs to act. Examples are a walk that raised, an undo not established that leaves production changed, and a war-room line that will never be delivered. Logged with the stack trace where an exception is in hand. Expected bad input is never an ERROR.
- **WARNING**: an unexpected condition the process recovered from or degraded around. Examples are a fallback taken, a source unreadable with the walk carrying on, a model answer truncated or malformed and asked again, and a payload rejected.
- **INFO**: a lifecycle milestone or a business event: a process started or stopped, an incident opened, a run claimed, a status changed, a production change made or put back, a verdict, a PR opened, a walk ended. INFO SHALL NOT be written inside a loop that runs per item, per poll or per minute.
- **DEBUG**: diagnostic context, which includes branch decision points (a candidate skipped, an answer reordered, a window clamped) and internal state.

Payload-level detail SHALL NOT be logged. It belongs in spans, which already carry each model call's messages.

#### Scenario: A run fails
- **WHEN** a walk raises out of the worker
- **THEN** one ERROR record carries the exception's stack trace

#### Scenario: A source is unreadable and the walk carries on
- **WHEN** a lookup the walk can do without raises, and the walk carries on
- **THEN** one WARNING record names what failed

#### Scenario: A production change is made
- **WHEN** the write MCP server performs a reversible action
- **THEN** one INFO record names the action and what it changed

#### Scenario: A candidate is skipped
- **WHEN** the walk passes over a candidate mitigation
- **THEN** the record of it is at DEBUG

### Requirement: A process says it started, stopped or died
The telemetry a process's `main` starts SHALL be a context manager:
- on entry, it logs INFO that the service started;
- on a normal exit, or a stop by signal or interrupt, it logs INFO that the service stopped;
- when an exception escapes, it logs CRITICAL with the stack trace and lets the exception propagate.

In every case it flushes before the process ends.

#### Scenario: An exception escapes main
- **WHEN** an exception escapes the body of a process's telemetry context
- **THEN** a CRITICAL record with the stack trace is in that process's `logs.jsonl`, and the exception propagates

#### Scenario: A clean stop
- **WHEN** a process's `main` returns
- **THEN** its `logs.jsonl` ends with an INFO record that the service stopped

### Requirement: Logging is configured once per process
`start_telemetry` SHALL configure stdlib logging for the process:
- it sets the root logger's level from the `LOG_LEVEL` setting, which defaults to `INFO`;
- it installs the OTel log handler;
- it installs a console handler that writes from a background thread through a queue, so console I/O never blocks the thread that logged.

No other code SHALL call `logging.basicConfig`, except the schema job, which starts no telemetry because the kernel it lives in depends on nothing else in the workspace. The loggers `httpx`, `httpx2`, `httpcore`, `httpcore2`, `mcp` and `uvicorn.access` SHALL be held at WARNING, whatever `LOG_LEVEL` says.

#### Scenario: Default level
- **WHEN** a process starts with `LOG_LEVEL` unset
- **THEN** INFO records reach the console and `logs.jsonl`, and DEBUG records reach neither

#### Scenario: Level lowered for an incident
- **WHEN** `LOG_LEVEL` is `DEBUG`
- **THEN** DEBUG records from Argus's own loggers reach the console and `logs.jsonl`

#### Scenario: Third-party chatter
- **WHEN** httpx logs a request at INFO
- **THEN** that record reaches neither the console nor `logs.jsonl`

### Requirement: Context is key-value, never concatenated
A record's message SHALL be a fixed phrase naming the event. The values it concerns SHALL be passed as record attributes through `extra`, never formatted into the message. The console line SHALL print every such attribute as `key=value` after the message, and `logs.jsonl` SHALL carry them as log record attributes.

#### Scenario: An action taken
- **WHEN** the write MCP server logs a scale-out from 3 to 6 replicas
- **THEN** the message is the same phrase for every scale-out, and the replica counts are attributes of the record

### Requirement: A record says whose work it was
Every log record SHALL carry, as attributes, each of `argus.incident.id`, `argus.run.id` and `argus.agent` that the current OTel baggage holds. The values SHALL come from the baggage, so a record written inside an MCP tool call made from a walk carries the walk's incident. A record written outside any incident SHALL carry none of them.

#### Scenario: A record inside an agent's step
- **WHEN** code inside the Investigator's step logs
- **THEN** the record carries the incident id, the run id and `argus.agent` set to the Investigator

#### Scenario: A record inside a tool call
- **WHEN** a read MCP server tool handler logs while serving a call made from a walk
- **THEN** the record in the server's `logs.jsonl` carries the walk's incident id

#### Scenario: A record outside any incident
- **WHEN** the index's catch-up loop logs
- **THEN** the record carries no `argus.incident.id`

### Requirement: Secrets never reach a log
A record attribute whose name says it holds a secret (containing `token`, `secret`, `password`, `api_key` or `authorization`, in any case) SHALL be replaced by `[redacted]` before any handler sees it. No call site SHALL pass a secret setting's value to a logger in any form.

#### Scenario: A token passed as context
- **WHEN** a record is logged with an attribute named `slack_token`
- **THEN** both the console and `logs.jsonl` show it as `[redacted]`

### Requirement: The servers' loggers reach the root
`argus_web` and both MCP servers SHALL run uvicorn without uvicorn's own logging configuration, so that the `uvicorn` and `uvicorn.error` loggers propagate to the root logger and reach `logs.jsonl`.

#### Scenario: argus_web starts
- **WHEN** `argus_web` starts serving
- **THEN** uvicorn's startup record is in `argus-web`'s `logs.jsonl`
