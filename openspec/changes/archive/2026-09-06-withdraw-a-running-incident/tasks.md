Under TDD: every task below is implemented against a test proposed in chat and
added by the user first, except where it says otherwise. Tasks in the demo app
are covered afterwards rather than before, per the repo's convention.

## 1. The status

- [x] 1.1 Add `WITHDRAWN` to `IncidentStatus` and to the terminal statuses, in
      `argus_core.models.incident_status`
- [x] 1.2 Confirm `status_after` never returns it, and that every existing
      reader of "has this ended" treats it as ended

## 2. Withdrawing

- [x] 2.1 `incidents.withdraw(conn, incident_id, actor)` in the orchestrator's
      repository: writes the status and the end time in one transaction where
      the incident is non-terminal, answers whether it took effect, and is a
      no-op for a terminal one
- [x] 2.2 The transition is recorded on the timeline with the actor the caller
      names, `Actor.HUMAN` being the one the door exists for
- [x] 2.3 An orchestrator entrypoint `withdraw_incident(incident_id)` that
      argus_web and the e2e suite both call - the one door. Its own module,
      `orchestrator.withdrawal`, for `intake`'s reason: what `argus_web` can
      import must reach nothing that walks

## 3. The walk stops

- [x] 3.1 `with_status` re-reads the incident's persisted status *before* the
      node runs, and where it is terminal runs nothing and writes nothing -
      reporting `withdrawn` into the state rather than swallowing it, since a
      node that changed nothing leaves the routers choosing the same route
      forever
- [x] 3.2 The graph stops rather than routing onward when it finds the incident
      withdrawn - no further node, no action proposed, no round opened, no
      postmortem. `stopping_when_withdrawn` wraps every router at
      registration, and every conditional mapping carries `WITHDRAWN_ROUTE: END`
- [x] 3.3 `agent_mitigation` takes an injected `still_wanted` predicate,
      defaulting to always true, and its recovery loop ends without a verdict
      when it answers false - `Verdict.WITHDRAWN`, carrying the undo descriptor
      of a flag deliberately left as set
- [x] 3.4 The orchestrator supplies the real predicate, reading the incident's
      status
- [x] 3.5 A candidate abandoned mid-verification is not marked tested and gets
      no verdict, while its action row still records the change and its undo

## 4. The undo

- [x] 4.1 Not needed. The descriptor already records `was_enabled = not
      enabled`, so the value Argus wrote is `action.enabled`; a `set_to` field
      would be a third copy of one bit, and a third thing that can drift
- [x] 4.2 A flag reader is injected into `agent_mitigation` so an undo can ask
      what the flag currently holds - `read_mcp_client.get_enabled_flags`,
      because asking what the world holds is a retrieval
- [x] 4.3 `_undone` becomes conditional: restore only where the flag still
      holds what Argus wrote; otherwise leave it and report it as changed from
      outside; report separately where the state could not be read
- [x] 4.4 The three outcomes reach the action row and the timeline, each saying
      which of the three it was
- [x] 4.5 The withdrawal's unwind runs every action the incident recorded as
      taken through that same conditional undo - `orchestrator.unwinding`,
      which owns the process while `agent_mitigation.undo_change` owns the
      capability. Nothing is filtered by outcome: a change already put back
      reads as one somebody else changed, so the unwind is idempotent for free

## 5. The queue

- [x] 5.1 A claimed run whose incident is terminal is unwound and settled
      rather than walked
- [x] 5.2 A queued run for a withdrawn incident is settled without the graph
      being invoked
- [x] 5.3 A run abandoned by a dead worker on a withdrawn incident is unwound
      when its lease expires, by the same path - the existing lease reclaim
      hands it to `take_one_run`, which asks the same two questions

## 6. The page

- [x] 6.1 A withdrawal endpoint on `argus_web` that names the incident and
      decides nothing, answering with what the orchestrator decided - `409` for
      an incident that has already ended, `404` for one nobody has
- [x] 6.2 A withdraw control on a live incident, absent on a terminal one,
      behind a deliberate confirmation. Inside the polled fragment, so it goes
      away by itself the moment the incident ends
- [x] 6.3 A withdrawn incident renders as withdrawn, distinguishable from
      resolved and escalated, showing which actions were put back and which
      were left as found - no template change needed: the unwind writes those
      as timeline notes and `timeline.html` already renders them

## 7. The e2e suite

- [x] 7.1 Propose the `tests/e2e/conftest.py` teardown in chat, whole file: 
      withdraw every live incident, wait for runs to settle under a loud
      timeout, truncate every table by asking the database, then the four
      world-resetting steps already there
- [x] 7.2 Propose the e2e case for withdrawal itself - an incident withdrawn
      mid-walk stops, puts its flag back, and reads as withdrawn
- [x] 7.3 Propose the case for a flag changed from outside being left alone
- [x] 7.4 Confirm `e2e_replay` is green, and that the double's queue is drained
      by exactly the case that seeded it

## 8. Settling up

- [x] 8.1 Dropped. Judging recovery relatively changed which verdict the
      minutes earn, not how many of them have to pass: the wait skips to the
      first whole minute after the action, that minute has to complete, be
      scraped and be published, and a minute still shedding the last of the
      outage pushes it to the next one. Three to four minutes before a working
      mitigation can read as recovered, on an idle machine. Six is the headroom
      over that, and the only thing it costs is wall-clock on the cases that
      genuinely wait it out
- [x] 8.2 `docs/spec-and-architecture.md`: withdrawal in the lifecycle and the
      status diagram, written as though it were always the intent
- [x] 8.3 A full sweep, green
