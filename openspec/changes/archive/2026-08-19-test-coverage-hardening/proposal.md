## Why

A test-coverage audit surveyed every module in the workspace for unit/integration gaps. Most flagged items didn't survive scrutiny once checked against a simple question - is there real, non-stub logic here that isn't already exercised by e2e? Nearly everything found was either a pure stub with no branching to test, logic currently unreachable given an upstream stub, or already fully covered end-to-end. Two items survived: `orchestrator/persistence.py` had zero direct test coverage for its DB read/write logic (already closed - see the `integration tests for persistence` commit), and `investigator_node` wraps genuinely real logic (`agent_investigator.investigate()` stopped being a stub in `investigator-hypothesis-loop` and now does real, input-dependent cause detection) that currently can't be tested in isolation, because the node calls it via a hardcoded import rather than an injectable dependency.

## What Changes

- (Done) Add integration test coverage for the `orchestrator/repository` package (formerly `persistence.py`): a local `Scenario`-based test framework under `modules/orchestrator/tests/repository/`, and a `conftest.py` fixture that brings up Postgres automatically for these tests.
- (Pending) Make `investigator_node`'s `investigate` dependency injectable (default-parameter injection, mirroring the `fetch_logs` pattern already used inside `agent_investigator.investigate()` itself), then add direct test coverage for `investigator_node`'s own logic - confidence-threshold routing and repository persistence wiring - independent of a live Target Service.

Explicitly out of scope (assessed during the audit and rejected):
- `agent_mitigation`/`agent_postmortem` - pure stubs (`mitigate()` always returns `"confirmed"`, `write_postmortem()` always returns the same fixed dict), nothing to drive.
- `mitigation_node`/`postmortem_node` - wrap those same stubs; their untested branches (e.g. `mitigation_node`'s "refuted"/"escalated" outcomes) are currently unreachable given today's stub constants.
- `codefix_node`/`propose_fix()`, `communicator_node`/`notify()` - unconditional `NotImplementedError` stubs.
- `argus_web/app.py` - deferred; better suited to component-level testing, and may already be adequately covered by the e2e suite.
- `argus_core`'s `config.py`/`db.py`/`schema.py` (config shouldn't be pinned by tests; schema is already exercised via e2e) and `llm.py`/`mcp.py` (unused stubs).

## Capabilities

### New Capabilities
- `node-testability`: orchestrator graph nodes with real (non-stub) logic can be tested directly, independent of live external services, via injectable dependencies - and the persistence/repository layer has integration test coverage for its core read/write paths.

### Modified Capabilities
(none - no externally-observable behavior changes; this is test coverage plus an internal dependency-injection refactor)

## Impact

- `modules/orchestrator/src/orchestrator/repository/`: integration test coverage added (done).
- `modules/orchestrator/tests/repository/`: new test files, local `Scenario` framework, `conftest.py` (done).
- `modules/orchestrator/src/orchestrator/graph.py`: `investigator_node` gains an injectable `investigate` parameter (pending).
- `modules/orchestrator/tests/`: new direct test coverage for `investigator_node`'s routing/persistence logic (pending).
