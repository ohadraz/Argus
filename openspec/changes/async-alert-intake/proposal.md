## Why

The alert webhook runs the whole incident inside the request that announced it:
`receive_alert` is a synchronous handler calling `create_incident_and_run`,
which invokes the graph to completion - every model round, every MCP call,
every mitigation attempt - before the response is written. The caller's
connection is held open for the length of the investigation and one FastAPI
threadpool worker with it, so two concurrent alerts are a capacity problem and
a slow model is a gateway timeout that abandons a run nobody is left to
receive. The endpoint already answers `202 Accepted`, which is a promise the
code does not keep.

It is also what makes the checkpointer worth nothing. LangGraph's Postgres
saver exists so a run can be resumed after the process that started it stopped;
nothing here can resume one, because the only handle on a run is a request that
has already failed.

## What Changes

- The alert webhook creates the incident, publishes `AlertAcknowledged`, hands
  the run to a worker, and returns `202` with the incident id - without waiting
  for the graph.
- **BREAKING** an incident's first status is `acknowledged` rather than
  `investigating`; `investigating` is written by the worker that takes the run.
  The interval between the two is how long the incident waited to be picked up.
- **BREAKING** for anything that read the webhook's response as proof the
  incident had finished. Nothing in Argus does: the live view polls, and the
  e2e suite waits on incident state rather than on the response.
- The Orchestrator's entrypoint separates starting an incident from running it,
  so the run is something a worker can be given - and, later, something a
  restart can pick up.
- A run that fails inside the worker leaves the incident recorded and its
  failure visible, rather than surfacing as a dropped HTTP connection.

## Capabilities

### New Capabilities

None. The behaviour changing is the lifecycle's, not a new one.

### Modified Capabilities

- `incident-lifecycle`: the webhook hands the run off and answers immediately
  rather than invoking the graph to completion within the request; the
  Orchestrator's entrypoint gains the seam between creating an incident and
  running it, and a run that fails is recorded rather than lost with the
  connection.
- `incident-lifecycle` also gains `acknowledged`: an accepted alert is recorded
  as held rather than as under investigation, and the incident becomes
  `investigating` when a worker takes its run.
- `flag-revert-mitigation`: an action is recorded before it is taken and at
  most once per candidate, so a walk resumed inside the mitigation node cannot
  act twice - and an action claimed but never answered for is settled by asking
  the flag provider whether the change landed.

## Impact

- `modules/argus_web/src/argus_web/app.py` - `receive_alert` returns after the
  handoff.
- `modules/orchestrator/src/orchestrator/entrypoint.py` -
  `create_incident_and_run` splits into creating the incident and running the
  graph for one.
- `tests/e2e/` and `modules/argus_web/tests/` - already wait on state rather
  than the response, so the change is expected to be visible to them only in
  timing.
- No schema change, no new dependency: the worker is whatever runs the graph
  off the request thread, chosen in `design.md`.
