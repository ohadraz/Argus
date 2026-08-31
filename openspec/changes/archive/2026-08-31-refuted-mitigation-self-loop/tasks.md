> Task 4.2 found that nothing writes `escalated` once the exhausted walk leaves
> for `fixing`: `codefix_node` returned no status, so the incident ended
> non-terminal and `tests/e2e/test_mitigation_directions.py` would have timed
> out. The fix was not a patch to this change - it was that nodes decided status
> at all. `status-reducer` took that decision out of them, and this change's
> remaining tasks pass on its tree. The two land together.

## 1. Agree the tests first

Tests are off-limits to Claude (`AGENTS.md`), so each of these is proposed whole
in chat and pasted by the human before the code under it is written.

- [x] 1.1 Propose the `argus_core` test that `IncidentStatus.FIXING` is
      non-terminal for the new reason - Code-Fix is working - replacing the
      comment in `modules/argus_core/tests/test_incident_status.py` that
      justifies it as a waypoint in the candidate walk.
- [x] 1.2 Propose the orchestrator unit test that a refuted mitigation returns
      `status = MITIGATING` and transitions the incident to `MITIGATING`, with
      no `FIXING` transition recorded and no `StatusChanged` carrying `fixing`
      published (spec: "A status is written only when the incident enters it").
- [x] 1.3 Propose the orchestrator unit test that the exhausted branch of
      `next_candidate_node` transitions to `FIXING` and returns
      `status = FIXING`.
- [x] 1.4 Propose the routing-test edits: `route_after_mitigation("mitigating")`
      is `"next_candidate"` (replacing the `"fixing"` case at
      `modules/orchestrator/tests/test_graph_routing.py:50`), and
      `route_after_next_candidate("fixing")` is `"fixing"`.
      `route_after_codefix("fixing") == "escalated"` is unchanged and stays.

## 2. Correct the statuses

- [x] 2.1 `_status_after` in `modules/orchestrator/src/orchestrator/graph.py`:
      map `Verdict.REFUTED` to `IncidentStatus.MITIGATING`. Update the
      surrounding comment in `mitigation_node` if it names `fixing`.
- [x] 2.2 `route_after_mitigation`: key the `"next_candidate"` route on
      `IncidentStatus.MITIGATING` instead of `FIXING`, and rewrite the docstring
      - it currently explains `fixing` as where a refuted action goes, which is
      the thing being removed.
- [x] 2.3 The exhausted branch of `next_candidate_node`: transition to and
      return `IncidentStatus.FIXING` instead of `ESCALATED`, keeping the
      `action`/`result` text as-is since it already describes running out of
      explanations.
- [x] 2.4 `route_after_next_candidate`: return `"fixing"` for
      `IncidentStatus.FIXING`. Drop the unreachable `"escalated"` fallthrough
      only if nothing can produce it - verify against the node's three returns
      before removing.
- [x] 2.5 `build_graph`'s `next_candidate` edge map: rename the `"escalated"`
      key to `"fixing"`, still pointing at the `codefix` node. Verify the graph
      still compiles and its node set is unchanged.

## 3. Correct the reasoning that outlived the bug

- [x] 3.1 `IncidentStatus.is_terminal` docstring in
      `modules/argus_core/src/argus_core/models/incident_status.py`: `fixing` is
      non-terminal because Code-Fix is still working, not because it is where a
      refuted action asks for the next candidate. Return value unchanged.
- [x] 3.2 `docs/spec-and-architecture.md` section 10: update the state diagram's edges
      so `mitigating` self-loops on a refutation and `fixing` is entered from
      the end of the walk. Follow the `spec-doc-style` skill - describe the
      design as though it were always the intent, no note about what changed.

## 4. Verify

- [x] 4.1 `uv run python -m nox -s "test_module(module='orchestrator')"` and
      `"test_module(module='argus_core')"`.
- [x] 4.2 Read `tests/e2e/test_mitigation_directions.py` for any assertion on a
      literal status set rather than `is_terminal()` (design.md, third risk). If
      one exists, propose the edit in chat rather than editing it.
- [x] 4.3 `uv run python -m nox -s lint typecheck`.
- [x] 4.4 `uv run python -m nox -s e2e_replay` - the walk's statuses are exactly
      what the replayed run exercises.

