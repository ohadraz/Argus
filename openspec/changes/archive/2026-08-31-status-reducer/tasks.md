> Builds on the paused `refuted-mitigation-self-loop` working tree, which is
> unit-green at 13/15. That change's status *values* are the starting point;
> this change moves where they are decided. It resumes at its task 4.3 once this
> lands.

## 1. The reducer, in isolation

Tests are off-limits to Claude (`AGENTS.md`): each is proposed whole in chat and
pasted before the code under it is written.

- [x] 1.1 Propose the `argus_core` tests for `status_after(state)` - one per
      scenario in `specs/incident-status-derivation/spec.md`: confirmed ->
      `resolved`, refuted with a candidate left -> `mitigating`, out of
      candidates with rounds left -> `investigating`, out of both -> `fixing`,
      an action that could not be taken -> `escalated`, a low-confidence
      investigation -> `escalated`, a fix found -> `resolved`.
- [x] 1.2 Write `status_after` in `modules/argus_core/src/argus_core/models/`,
      beside `IncidentStatus`. Pure, total, no fallback branch - every path an
      explicit return.
- [x] 1.3 Export it from `argus_core`'s public API. `orchestrator` and
      `argus_web` both read the FSM's meaning; neither may reach into a private
      name for it.

## 2. Split transition from note

- [x] 2.1 Propose the `orchestrator` repository test that `record_note` writes a
      `TimelineEvent` row and leaves `Incident.status` untouched.
- [x] 2.2 Add `incidents.record_note(conn, incident_id, actor, action, result,
      confidence)` in `modules/orchestrator/src/orchestrator/repository/
      incidents.py`, writing the timeline row alone with the incident's current
      status. `incidents.transition` keeps its contract unchanged.
- [x] 2.3 Add the `RecordNote` Protocol and `_record_note` default beside
      `TransitionIncident` in `graph.py`.

## 3. The wrapper

- [x] 3.1 Propose the tests for the wrapper: an unchanged derived status
      persists and publishes nothing; a changed one persists and publishes
      exactly once; narration is recorded either way; the actor comes from
      registration.
- [x] 3.2 Write the wrapper in `graph.py`. It takes a node function, an `Actor`,
      and the injectable `transition_incident` / `record_note` / `publisher`
      seams; runs the node, merges its updates onto the state, applies
      `status_after`, and writes the transition only on a difference.
- [x] 3.3 Apply it in `build_graph` at each `add_node` call, passing the actor
      each node belongs to.

## 4. Strip status out of the nodes

Each of these is: propose the test edit, then make the node return work and
narration only. Do them one at a time - the suite stays runnable between.

- [x] 4.1 `tier_gate_node` - drop `transition_incident`, keep the rejection as
      narration, keep `record_outcome`, return `{"proposed_action": None}`.
- [x] 4.2 `investigator_node` - drop the status from its return and its
      `transition_incident` call.
- [x] 4.3 `mitigation_node` and `_nothing_to_act_on` - same, and delete
      `_status_after(verdict)`, which the reducer subsumes.
- [x] 4.4 `next_candidate_node` - all three branches. Confirm the state it
      writes (`hypothesis`, `candidate_index`, `rounds`) is enough for the
      reducer to reach the same three answers (design.md, second risk).
- [x] 4.5 `codefix_node` - return whether a fix was found, so the reducer can
      conclude `resolved` or `escalated`. Still a stub; the return is the honest
      part.

## 5. Verify

- [x] 5.1 `uv run python -m nox -s "test_module(module='argus_core')"` and
      `"test_module(module='orchestrator')"`.
- [x] 5.2 `uv run python -m nox -s lint typecheck`.
- [x] 5.3 Confirm no node returns a `status` key and no node calls
      `transition_incident` - grep both, in `graph.py` and in any other module.
- [x] 5.4 `uv run python -m nox -s e2e_replay`. This is the first run that
      exercises the exhausted walk end to end, and the gap that paused
      `refuted-mitigation-self-loop` is what it proves closed.
- [x] 5.5 Resume `refuted-mitigation-self-loop` at its task 4.3. Both its
      remaining tasks pass on this change's tree - the two land together.

