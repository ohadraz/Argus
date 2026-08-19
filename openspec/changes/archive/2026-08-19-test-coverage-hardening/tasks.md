## 1. Persistence/repository test coverage

- [x] 1.1 Add `orchestrator/repository/` package (from `persistence.py`) with typed
  Pydantic row models for reads
- [x] 1.2 Add a local `Scenario`/`assertions` test framework
  (`modules/orchestrator/tests/repository/framework/`) for given/when/then-style
  integration tests
- [x] 1.3 Add `modules/orchestrator/tests/repository/test_incidents.py` covering
  `create`, `transition`, `get` - including the atomic incident+timeline_event
  pairing
- [x] 1.4 Add `modules/orchestrator/tests/repository/conftest.py` - an autouse,
  session-scoped fixture that brings up Postgres and creates the schema
  automatically for these tests
- [x] 1.5 Split `docker-compose.yml`'s `target-service` into an `e2e` Compose
  profile, so bringing up just Postgres (for the repository tests) doesn't
  require the unrelated demo fixture

## 2. investigator_node testability

- [x] 2.1 Add an injectable `investigate` parameter to `investigator_node`
  (default: the real `agent_investigator.investigate`), matching the
  `fetch_logs` pattern already used inside `agent_investigator.investigate()`
  itself
- [x] 2.2 Add a direct test for `investigator_node`'s confidence >= threshold
  path (routes to `mitigating`, correctly calls
  `hypotheses.record`/`incidents.transition`)
- [x] 2.3 Add a direct test for `investigator_node`'s confidence < threshold
  path (routes to `escalated`, correctly calls
  `hypotheses.record`/`incidents.transition`)
- [x] 2.4 Confirm `nox -s test_module -- orchestrator`, `nox -s typecheck`,
  `nox -s lint`, and the full `nox -s e2e` suite all still pass
