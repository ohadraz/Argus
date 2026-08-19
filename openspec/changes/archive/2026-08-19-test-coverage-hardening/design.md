## Context

A test-coverage audit surveyed every module for unit/integration gaps. Most findings didn't survive scrutiny once checked against a simple question: is there real, non-stub logic here that isn't already exercised by e2e? `orchestrator/persistence.py` (since renamed to `orchestrator/repository/`) was the one clear gap and has already been closed. `investigator_node` is the one remaining item: it wraps `agent_investigator.investigate()`, which stopped being a stub in `investigator-hypothesis-loop` and now does real, input-dependent cause detection - but `investigator_node` calls it via a hardcoded module-level import, so any direct test of the node's own logic (confidence routing, repository writes) currently requires a live Target Service, the same constraint `investigate()` itself had before its `fetch_logs` parameter made it injectable.

## Goals / Non-Goals

**Goals:**
- (Done) `orchestrator/repository/` has integration test coverage - already landed.
- `investigator_node` accepts an injectable `investigate` dependency (default parameter, mirroring `agent_investigator.investigate()`'s `fetch_logs` pattern), defaulting to the real `agent_investigator.investigate`.
- Direct (non-e2e) test coverage for `investigator_node`'s own logic: given a stubbed `investigate` result, does it correctly compute `next_status` (confidence >= threshold vs. below), and does it correctly call `hypotheses.record`/`incidents.transition` with the right arguments?

**Non-Goals:**
- Everything the audit rejected (see proposal's out-of-scope list) - not revisited here.
- Any change to `investigate()`'s own behavior, or to the confidence values it returns.
- Testing `mitigation_node`/`postmortem_node` - still blocked on their own upstream stubs (`mitigate()`/`write_postmortem()`) becoming real; not something to force now.

## Decisions

**Injectable dependencies via default parameters on `investigator_node` itself, not a class.** `investigate`, `record_hypothesis`, `transition_incident` are default-argument parameters on the plain `investigator_node` function - matching `agent_investigator.investigate()`'s own `fetch_logs` seam exactly. A class-based (`InvestigatorNode.__init__`/`__call__`) design was tried and reverted: LangGraph only ever needs a plain `state -> dict` callable, and the class added ceremony without a matching benefit once tests could inject function-shaped defaults directly.

**Typed contracts via `Investigate`/`RecordHypothesis`/`TransitionIncident`, resolving the Open Question below.** `RecordHypothesis` and `TransitionIncident` are `Protocol` classes (not plain `Callable[...]` aliases), specifically so `unittest.mock.create_autospec` can target them directly in tests - a `Callable[...]` alias isn't introspectable at runtime, but a `Protocol`'s `__call__` method is.

**`unittest.mock.create_autospec` allowed as the test double - `patch()` is not.** Tests pass `create_autospec(...)`-built mocks as the injected values, giving real (if runtime-only) call-signature validation. `unittest.mock.patch` stays off the table - it would target a module-level import instead of using the injected seam, and wouldn't even work correctly here regardless: default-argument values are captured once at function-definition time, so patching the underlying name after import has no effect on what the default already resolved to.

**Test lives at `modules/orchestrator/tests/orchestrator/test_graph.py`, mirroring the source module's own path** (`orchestrator/graph.py`) - not the `repository/` subdirectory (DB-layer tests only) and not root `tests/integration/` (single-module concern). Shared test infrastructure (`Scenario`, `assertions`, `matchers`, `builders`) lives in `modules/orchestrator/tests/framework/`, reusable by future test files in this module.

**No real DB, no live Target Service.** `record_hypothesis`/`transition_incident` mocks assert on call arguments directly; nothing in this test touches Postgres or extends `repository/conftest.py`'s fixture reach. The repository/DB integration coverage from task 1 remains the only place that verifies actual persistence.

## Risks / Trade-offs

- **[Risk]** `mitigation_node`/`postmortem_node` remain untestable in the same way once their own stubs eventually become real → **Mitigation**: explicitly out of scope for now; revisit with the same DI pattern established here when `mitigate()`/`write_postmortem()` gain real logic.

## Migration Plan

N/A - additive only (a new parameter with a default value, new test files).

## Open Questions

- ~~Should the `investigate` injection point use a named type alias (matching `agent_investigator`'s `LogFetcher`) for readability?~~ Resolved during implementation: yes - `Investigate` (a `Callable` alias) and `RecordHypothesis`/`TransitionIncident` (`Protocol` classes, needed for `create_autospec` support and keyword-argument signatures).
