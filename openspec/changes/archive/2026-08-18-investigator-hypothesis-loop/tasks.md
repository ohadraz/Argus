## 1. Driving test

- [x] 1.1 Add the failing e2e test `tests/e2e/test_scenario_investigation.py`
  that seeds the `feature-flag-toggle` scenario, fires the alert, and asserts
  `cause_type == "feature-flag-toggle"` on the resulting hypothesis (already
  done, confirmed red: `AssertionError: Expected cause_type
  ['feature-flag-toggle'], got [None].`)

## 2. CauseType enum

- [x] 2.1 Add a `CauseType` to `argus_core` (`argus_core/models/cause.py`) -
  implemented as a `Literal` type alias + a named constant
  (`FEATURE_FLAG_TOGGLE: CauseType = "feature-flag-toggle"`) rather than a
  `str Enum`, matching this codebase's existing `IncidentStatus` convention
  (also a bare `Literal` alias) instead of introducing a new pattern

## 3. Target Service config wiring

- [x] 3.1 Add a `TARGET_SERVICE_URL` setting to `argus_core.config.Settings`,
  defaulting to `http://localhost:8080` (design.md: matches how the
  non-containerized local `argus_web` process already reaches the Target
  Service during e2e)

## 4. Investigator log-reading + cause detection

- [x] 4.1 Add `httpx` as a real (non-dev) dependency of `agent_investigator`'s
  `pyproject.toml` (design.md's flagged risk: it's currently only available
  via the workspace dev group)
- [x] 4.2 Add a function that calls `GET {TARGET_SERVICE_URL}/logs` and
  returns the log lines
- [x] 4.3 Add deterministic keyword-matching: logs containing "feature flag"
  (case-insensitive) alongside an `ERROR`-level line → `CauseType.FEATURE_FLAG_TOGGLE`
  at the same confidence the stub previously always returned (spec:
  "Feature-flag-toggle logs are recognized")
- [x] 4.4 Fall back to `cause_type = None` at that same confidence when
  nothing matches (empty logs or unrecognized content), preserving
  `test_incident_lifecycle.py`'s existing passing behavior (spec: "No
  recognizable logs fall back to an undetermined cause")
- [x] 4.5 Update `investigate()`'s return shape to also carry the determined
  `cause_type` (or `None`) alongside the existing hypothesis text and
  confidence
- [x] 4.6 `_determine_cause` now requires the flag-toggled-on event to
  precede the first error in log order, not just both being present -
  `modules/agent_investigator/tests/test_investigate.py`'s
  `test_investigate_does_not_attribute_an_error_that_precedes_the_toggle`
  confirmed red, then implemented against

## 5. Persistence

- [x] 5.1 Update `record_hypothesis` (`orchestrator/persistence.py`) to
  accept and write `cause_type` to the `hypothesis` table's `cause_type`
  column (spec: "cause_type is persisted on the hypothesis row")
- [x] 5.2 Update `investigator_node` (`orchestrator/graph.py`) to pass the
  determined `cause_type` through to `record_hypothesis`

## 6. Verification

- [x] 6.1 Run `uv run python -m nox -s e2e` and confirm both
  `tests/e2e/test_incident_lifecycle.py` and
  `tests/e2e/test_scenario_investigation.py` pass
- [x] 6.2 Confirm every requirement in
  `specs/investigator-cause-detection/spec.md` and the modified
  `incident-lifecycle` requirement is satisfied by manually walking each
  scenario
- [x] 6.3 Run `uv run nox -s typecheck` and `uv run nox -s lint`, confirm both
  clean
