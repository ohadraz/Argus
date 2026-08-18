## Context

`agent_investigator` (`modules/agent_investigator/src/agent_investigator/__init__.py`, 17 lines) is currently a pure function of the alert - `investigate(alert) -> (hypothesis: str, confidence: float)` - that always returns the same hardcoded string and `0.9` confidence. The orchestrator's `investigator_node` (`modules/orchestrator/src/orchestrator/graph.py`) calls it, persists the result via `record_hypothesis`, and routes to `mitigating` if confidence >= `MITIGATE_THRESHOLD = 0.75`, else `escalated`.

The `hypothesis` table already has a `cause_type` column (`modules/argus_core/src/argus_core/schema.py`), defined but never written. The Target Service (`Argus-Demo-Target-App`) exposes `GET /logs` (returns the active scenario's pre-seeded log lines, or `[]` if none active) and `POST /scenario/seed` - both already built, from `target-service-scenario-and-logs`. Nothing in Argus today calls the Target Service at all - no base-URL config exists anywhere in `argus_core.config.Settings`.

The driving e2e test, `tests/e2e/test_scenario_investigation.py`, is already written and confirmed red: it seeds the `feature-flag-toggle` scenario, fires an alert, and asserts `hypothesis.cause_type == "feature-flag-toggle"` for the resulting incident.

## Goals / Non-Goals

**Goals:**
- `agent_investigator` calls the Target Service's `GET /logs` and inspects the returned log lines.
- A `CauseType` enum in `argus_core` (one member: `FEATURE_FLAG_TOGGLE = "feature-flag-toggle"`), used instead of a bare string literal wherever the cause is produced or checked.
- Deterministic keyword matching: if the returned logs contain the phrase "feature flag" (case-insensitive) alongside an `ERROR`-level line, report `CauseType.FEATURE_FLAG_TOGGLE` at a high, fixed confidence.
- `record_hypothesis` (`orchestrator/persistence.py`) writes `cause_type` to the `hypothesis` table - it already writes `description`/`confidence`, just never `cause_type`.
- A `TARGET_SERVICE_URL` setting on `argus_core.config.Settings`, defaulting to `http://localhost:8080` - matching docker-compose's host-mapped port, since `argus_web`/the orchestrator run as a local (non-containerized) process during e2e (`noxfile.py`'s `_start_argus_web()`), reaching the Target Service the same way the e2e test itself does.

**Non-Goals:**
- The `bad-deployment` scenario - no driving test exists for it yet (tracked as a follow-up).
- Any real LLM call / ReAct reasoning loop - keyword matching only, for this slice.
- A real `logs-mcp` server - `agent_investigator` calls `/logs` directly via `httpx`; `argus_core/mcp.py`'s client stays an unused placeholder.
- Changing `MITIGATE_THRESHOLD` or escalation semantics themselves - out of scope, tracked separately per spec's own open question about tuning these against benchmark results.
- A UI, Slack integration - already parked (see project memory).

## Decisions

**Plain `httpx` call to the Target Service, not through `argus_core.mcp`.** `argus_core/mcp.py`'s `StubMCPClient.call_tool` raises `NotImplementedError` - it's explicit walking-skeleton filler, not a real integration point. Building a real `logs-mcp` server first would be a substantially larger, separately-scoped change (already deferred in `target-service-scenario-and-logs`'s non-goals). `argus_web`'s webhook and the e2e tests already reach services directly via `httpx`; `agent_investigator` does the same for consistency with the rest of the codebase at this stage.

**The "no recognized cause" fallback keeps today's stub confidence (0.9), not a new low value.** This is the one non-obvious decision in this change. `tests/e2e/test_incident_lifecycle.py` (untouched, deliberately - see `investigator-hypothesis-loop`'s proposal) never seeds a scenario, so its alert hits an empty `/logs` response and no keyword match. If the fallback used a low confidence to signal "genuinely unknown," that test's asserted `investigating → mitigating → resolved` sequence would break, since it would now route to `escalated` instead. Rather than touch that test (it deliberately tests FSM shape, independent of any specific scenario) or weaken this change's own test, the fallback path preserves the exact confidence the stub always returned, with `cause_type` left `NULL` (accurately: no cause was determined) exactly as it is today. Alternative considered: give the fallback a low confidence to make "unknown" meaningfully distinct from "diagnosed" - rejected for now, since MITIGATE_THRESHOLD tuning against real signal is explicitly a separate, already-tracked concern (spec's own open question on tuning these values against benchmark results), not something to redesign as a side effect of this change.

**`CauseType` is a `str` `Enum`, not a plain string constant.** Both `agent_investigator`'s matching logic and `record_hypothesis`'s DB write use `.value`, so the DB column (`TEXT`) and the wire-level scenario id from the Target Service stay plain strings, while Argus-side code gets type safety and one canonical source instead of a magic string repeated across the Investigator and the e2e test (already agreed and tracked in project memory).

**Keyword match requires "feature flag" AND an `ERROR`-level line, not just the phrase alone.** The `feature-flag-toggle` scenario's own pre-seeded logs include `INFO`-level lines mentioning "feature flag" while it's still off (no incident). Matching on the phrase alone would misclassify a scenario in its healthy state as already diagnosed; requiring an `ERROR` line alongside it ties the match to the actual failure, not just topical mention.

**`TARGET_SERVICE_URL` defaults to `http://localhost:8080`, not a docker-internal hostname.** Matches the existing e2e setup exactly: `argus_web` (and therefore `agent_investigator`, called in-process from it) runs as a local `uvicorn` process outside docker-compose's network (`noxfile.py`), so it reaches the containerized Target Service via its host-mapped port, same as `tests/e2e/test_scenario_investigation.py` already does directly.

## Risks / Trade-offs

- **[Risk]** The "no recognized cause" fallback is behaviorally identical to the old stub (same confidence, same routing) - this change doesn't actually improve escalation behavior for genuinely-unknown incidents, only for the one scenario it recognizes → **Mitigation**: accepted, deliberately deferred (see Decisions above); this is expected to be revisited once confidence-threshold tuning is addressed as its own concern.
- **[Risk]** Keyword matching on raw log text is brittle - reordering or rewording the Target Service's pre-seeded log lines could silently break detection → **Mitigation**: accepted for this slice (matches the "deterministic, not LLM" decision already made); a real LLM-based reasoning loop is the intended eventual replacement, not a hardening of the keyword matcher itself.
- **[Risk]** `agent_investigator`'s `pyproject.toml` doesn't declare `httpx` as a dependency today (it's only in the workspace root's dev group) → **Mitigation**: add it as a real dependency of `agent_investigator`, not inherited from the dev group, since this module now needs it at runtime, not just in tests.

## Migration Plan

N/A - purely additive/replacing stub logic inside `agent_investigator` and `argus_core`; no data migration (the `cause_type` column already exists, just unpopulated for past rows). Rollback is reverting the stub.

## Open Questions

- Should the `CauseType` enum eventually move to a dedicated `modules/common/` package once a second module needs it, per this workspace's existing convention that shared logic belongs there rather than being duplicated? Not urgent - only `agent_investigator` and `argus_core` (which defines it) need it today.
- When `bad-deployment` detection is added later, does the keyword-matching approach stay as a chain of independent checks, or does it need a small dispatch structure? Deliberately left open until there's a second real case to design against.
