## Context

`argus_web` receives the alert and runs the incident inside the request that
delivered it. The endpoint says `202 Accepted` and then blocks for the whole
graph - model rounds, MCP retrieval, mitigation, verification - so the promise
in the status code is made by the signature and broken by the body.

Everything needed to do better is already here. The incident row exists before
the graph is invoked, the event stream is written from the graph rather than
from the request, and the live view polls. The checkpointer is already a
Postgres saver keyed by `thread_id = incident_id`, which means a run's state
outlives the process that produced it - and nothing in Argus can currently pick
one up, because the only handle on a run is an HTTP request that has already
timed out.

Argus's own services run as host processes started from `noxfile.py`; the e2e
stack brings up postgres and the Target Service in docker and Argus beside it.
A worker is one more such process.

## Goals / Non-Goals

**Goals:**

- The webhook answers as soon as the incident exists, with its id.
- A run survives the request that asked for it, and survives `argus_web`
  restarting.
- An unfinished run is picked up again rather than left half-walked - the thing
  the checkpointer was always for.
- A run that fails is recorded against its incident, visible in the same places
  every other incident fact is.

**Non-Goals:**

- Distributing work across machines. One worker process, and a claim protocol
  that would not corrupt anything if a second were started.
- A message broker. Postgres is already a dependency and already holds the
  incident.
- Changing what the graph does, what the sub-agents decide, or how status is
  derived. This change moves where the graph is invoked from, and nothing else.
- Cancelling or pausing a running incident from the UI.

## Decisions

**The queue is a table in the database that already holds the incident.**
A row per run, carrying the incident id, the alert that started it, the state
it is in (`queued`, `running`, `failed`, `done`), when it was claimed and by
whom. Postgres is the one piece of infrastructure Argus is guaranteed to have,
the run is meaningless without the incident it belongs to, and a table can be
read by the same admin looking at everything else. *Alternatives:* Redis or a
broker - a second thing to run, to configure and to explain, for a demo that
processes one incident at a time. In-process `BackgroundTasks` - rejected as
the goal here, since a run that dies with the web process is the failure being
fixed.

**A worker claims with `SELECT ... FOR UPDATE SKIP LOCKED`.** The standard
Postgres queue claim: two workers cannot take the same run, and a worker that
dies mid-claim releases its lock rather than wedging the row. The alternative -
"only one worker will ever run, so claim without locking" - is a correctness
argument resting on an operational promise, and those get broken by a restart
that overlaps.

**A claim carries a lease, and an expired lease is reclaimable.** A worker
killed mid-run leaves a `running` row nobody holds a lock on. The lease is what
lets the next worker tell that from a run genuinely in progress, and reclaiming
it is a `graph.invoke` on the same `thread_id` - the checkpointer replays what
was already done. This is the whole reason the checkpointer is in the design,
and until now nothing exercised it.

**The worker lives in `orchestrator`, not in a module of its own.** It invokes
the graph, and the graph is the orchestrator's. A separate module would either
depend on `orchestrator`'s internals or force the graph's construction into
`argus_core`, and neither buys anything: what makes the worker a separate
*process* is how it is started, not which package it is in.

**`argus_web` never invokes the graph, and never imports it.** The webhook
creates the incident, publishes `AlertAcknowledged` and enqueues the run - all
through the Orchestrator's entrypoint, exactly as it calls it today, so the
module boundary is unchanged and only what the call does behind it moves. The
web process losing the ability to run an incident is the point.

**A failed run is a recorded outcome, not a log line.** The worker marks the
run `failed` with the reason and leaves the incident where the graph left it.
An incident whose run failed is visibly unfinished rather than silently stuck
mid-investigation, which is the state the current code produces on a timeout.

**A resumed walk is stopped from acting twice by the database, not by a check.**
The action row is written *before* the action is taken, and `action` carries a
unique constraint on the incident and the candidate it was taken for. The
insert is therefore the claim: it succeeds for the walk that gets there first
and fails for any other, and the failure is what tells a resumed node that this
action has already been taken. Reading first and acting after - "is there a row
yet?" - would let two workers both read nothing and both act, which is the
race the claim on the run itself already refuses to rely on being unlikely.

**A claim with no outcome is answered by the provider, not by a guess.** A
worker that died between the insert and the completion leaves a row saying an
action was begun and not what came of it. Argus asks the provider whether the
change actually landed - the flag provider's event log is already how Argus
tells its own changes from a human's - and records the answer. Where the
provider cannot say, because it is unreachable or because the action type
leaves no audit trail, the incident escalates: every other answer available
here (assume refuted, assume nothing happened, do it again) is a guess written
into a column that reads as a measurement, and one of them is wrong the day an
action is not safe to repeat.

## Risks / Trade-offs

- **A worker that is not running means alerts pile up silently.** The webhook
  answers `202` whether or not anything will pick the run up → the run's state
  is queryable, and an incident with a `queued` run and no progress is visible
  as such; the e2e stack starts the worker with the rest of the services.
- **Polling costs a query per interval per worker.** → One worker, an interval
  in settings, and a table with an index on the state it filters by. `LISTEN` /
  `NOTIFY` would remove the poll and add a connection to keep alive; not worth
  it at this size, and easy to add behind the same claim protocol later.
- **A resumed run re-enters the graph at a checkpoint, not at the beginning.**
  Any node with a side effect that is not idempotent would repeat it. Mitigation
  actions are the ones that matter → the resume path is exercised in tests
  against a run killed mid-walk, and anything found to repeat is either made
  idempotent or moved behind a check of what the event stream already records.
- **Two processes now have to be up for a demo to work.** → `noxfile.py` starts
  both, as it already does for `argus_web` and the MCP servers; the same session
  that brings the stack up brings the worker up.
- **The lease turns a slow run into a duplicated one if it is set too short.**
  An investigation legitimately takes minutes → the lease is renewed while the
  run is alive rather than set once at claim time, and its length is derived
  from the same settings that bound the walk.
