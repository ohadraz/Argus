## Why

The Investigator is currently a stub (`agent_investigator/__init__.py`) - a pure function of the alert that always returns the same hardcoded hypothesis string and a fixed 0.9 confidence, regardless of what's actually happening. `target-service-scenario-and-logs` gave the Target Service pre-seeded, scenario-specific log content specifically so a later change could build a real Investigator against something genuine instead of synthetic data (per that change's own stated purpose) - this is that change. It replaces the stub with logic that reads the Target Service's `/logs` and determines a real root cause for the `feature-flag-toggle` scenario, closing the loop from "seeded scenario" to "diagnosed cause."

## What Changes

- Add an HTTP call from `agent_investigator` to the Target Service's `GET /logs` endpoint - a plain HTTP client call, not through the still-unbuilt `logs-mcp`/MCP abstraction (`argus_core/mcp.py`'s client is an explicit walking-skeleton placeholder that raises `NotImplementedError`; building a real MCP server is a separate, larger, already-deferred change).
- Add a `CauseType` enum to `argus_core` (one member for now: `FEATURE_FLAG_TOGGLE`), and wire `cause_type` through to the `hypothesis` table - the column already exists in the schema but is never written today.
- Add deterministic keyword-matching logic: recognizes the `feature-flag-toggle` scenario's log content and reports that cause_type at a high confidence; falls back to a low-confidence "unknown cause" result when nothing recognizable is found (exact values are a design.md decision).
- Add a `TARGET_SERVICE_URL` setting to `argus_core.config.Settings` - no such wiring exists today; defaults to match docker-compose's exposed port for local/e2e use.
- Driving test, already added and confirmed red as of this proposal: `tests/e2e/test_scenario_investigation.py`.

Explicitly **out of scope**: the `bad-deployment` scenario (deliberately deferred as a fast-follow, tracked separately), a real LLM-based ReAct reasoning loop, a real `logs-mcp` server, any change to Mitigation/Code-Fix/Communicator/Postmortem's stub behavior, a UI, Slack integration.

## Capabilities

### New Capabilities
- `investigator-cause-detection`: the Investigator can read the Target Service's current logs and determine a real `cause_type` for at least one known scenario, instead of always returning a fixed stub hypothesis.

### Modified Capabilities
- `incident-lifecycle`: the "FSM completes the investigating → mitigating → resolved happy path" requirement's scenario currently locks in "the Investigator stub returns a fixed hypothesis at confidence >= 0.75" - this changes to reflect real (non-stub) cause detection for the `feature-flag-toggle` scenario specifically, while stub behavior for Mitigation and the other sub-agents is unchanged.

## Impact

- `modules/agent_investigator`: real log-reading + cause-determination logic replaces the stub.
- `modules/argus_core`: new `CauseType` enum, new `TARGET_SERVICE_URL` setting, hypothesis persistence now writes `cause_type`.
- `tests/e2e/test_scenario_investigation.py`: new e2e test (already added, confirmed red).
- No changes to `Argus-Demo-Target-App` in this change - it already exposes everything needed (`/scenario/seed`, `/logs`).
