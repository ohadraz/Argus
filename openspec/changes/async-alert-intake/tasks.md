Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it.

## 1. The queue

- [x] 1.1 Propose the test: a run enqueued for an incident is claimed by one
      caller and not by a second one looking at the same moment.
- [x] 1.2 The `incident_run` table - incident id, state, claimed at, claimed by,
      failure reason - in the schema, with an index on the state a worker
      filters by.
- [x] 1.3 The runs repository: enqueue, claim with `FOR UPDATE SKIP LOCKED`,
      renew a lease, finish, fail. Named per the repository convention -
      `get()` only for a lookup by run id.
- [x] 1.4 Test: a claim whose lease has expired is reclaimable; one whose lease
      is live is not.

## 2. The handoff

- [x] 2.1 Propose the test: the webhook answers with an incident id while the
      graph has not run, and an enqueued run exists for that incident.
- [x] 2.2 `create_incident_and_run` splits into creating the incident (row,
      `AlertAcknowledged`, enqueued run) and running one, with the endpoint
      calling only the first.
- [x] 2.3 `argus_web` no longer reaches the graph at all - check the import
      graph, not just the call.

## 3. The worker

- [x] 3.1 Propose the test: a queued run is walked to a terminal status by the
      worker, with no request in flight.
- [x] 3.2 The worker loop in `orchestrator`: claim, renew while walking, invoke
      the graph on the incident's own `thread_id`, finish.
- [x] 3.3 Test: a run whose graph raises is recorded as failed with its reason,
      and the incident is not recorded as resolved.
- [x] 3.4 The poll interval and lease length in `argus_core.config`, derived
      from the settings that bound the walk rather than guessed, plus
      `.env.example`.

## 4. Resuming

- [x] 4.1 Propose the test: a run abandoned mid-walk is taken up again and
      continues from its recorded state rather than from the alert.
- [x] 4.2 Whatever the test needs of the claim path to make an abandoned run
      distinguishable from a live one on the worker's own boot.
- [x] 4.3 The unique constraint on `action (incident_id, hypothesis_id)`, and
      `record_action` reshaped into the insert that claims - called before the
      action is taken, answering whether this walk is the one that took it -
      with `complete_action` recording what came of it.
- [x] 4.4 Test: a resumed walk whose action is already recorded neither acts
      again nor announces a second attempt, and answers with the outcome
      already on file.
- [x] 4.5 Test: a claim with no outcome - a worker that died between the
      insert and the completion - is answered by asking the provider whether
      the change landed, and escalates where the provider cannot say.
- [x] 4.6 The provider question itself, over the flag provider's event log -
      the same source Argus already reads to tell its own changes from a
      human's.

## 5. Running the thing

- [x] 5.1 A nox session starting the worker beside `argus_web` and the MCP
      servers, per the `nox-session-style` skill.
- [x] 5.2 `e2e` and `e2e_replay` bring the worker up with the rest of the stack
      and tear it down with them.
- [x] 5.3 Test: the e2e stack still reaches a postmortem end to end, with the
      run walked by the worker.

## 6. Closing out

- [x] 6.1 `lint`, `typecheck`, `test_module` for each touched module, then
      `test_all`.
- [x] 6.2 `integration`, and `e2e_replay` in the background.
- [x] 6.3 Spec §7.1 and §7.9 updated for where the graph is invoked from, per
      the `spec-doc-style` skill.
- [x] 6.4 Re-read this change's delta specs against what was built before
      archiving.
- [ ] 6.5 One-line commit, approved before it is made.

## 7. Acknowledged, before anyone is on it

- [x] 7.1 Propose the test: an accepted alert leaves the incident
      `acknowledged`, and the timeline says so - nothing is investigating until
      a worker takes the run.
- [x] 7.2 `IncidentStatus.ACKNOWLEDGED`, non-terminal, and the intake writing
      it in place of `investigating`.
- [x] 7.3 Test: the worker's first act on a claimed run is the transition to
      `investigating`, recorded on the timeline.
- [x] 7.4 The transition itself, in `run_incident` before the graph is invoked.
- [x] 7.5 The status sequences every existing test asserts gain their leading
      `acknowledged`; the live page treats it as running rather than finished.
- [x] 7.6 §10's state machine and the `incident-lifecycle` delta.
      `incident-status-derivation` needs none: it derives a status from the
      graph's state, and `acknowledged` is written by the intake before the
      graph runs.
