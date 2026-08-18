## Why

`Argus-Demo-Target-App` currently only exposes a health check - nothing in it produces anything an Investigator could reason about. Per spec's own milestone order (§23), real Investigator work (a ReAct loop producing hypotheses "from logs") comes right after the Target Environment has *basic* endpoints - not after a full flag/metrics/log stack is built. This change gives the Target Service a small library of pre-seeded scenarios (§15.2's scenario control, §21.1's benchmark scenario list), each a fixed set of log entries simulating a different incident cause, and a way to read back whichever one is currently active (§16's log query endpoint) - so a later change can build a real Investigator against something genuine instead of synthetic data.

The Target Service does not simulate live behavior - it doesn't run a "business endpoint" whose real-time success/failure produces logs. It only returns pre-written log content, one fixed set per scenario, selected by scenario control. This corrects an earlier draft of this change that modeled a single live-toggled endpoint (`/flag-gated-operation`) - that was a misunderstanding of what was actually discussed, not the intended design.

## What Changes

- Add a small in-code registry of pre-seeded scenarios, each a fixed list of log entries representing what a real incident's logs would look like. Seed exactly two for this change, matching two distinct entries from spec §21.1's benchmark scenario list: `feature-flag-toggle` (#1) and `bad-deployment` (#2) - enough to prove the registry/selection mechanism genuinely generalizes beyond a single hardcoded case, without authoring all seven scenarios up front.
- Add scenario control (§15.2): `POST /scenario/seed` activates a named scenario by id, `POST /scenario/reset` deactivates it (back to no active scenario), `GET /scenario/status` reports which scenario (if any) is currently active.
- Add a log query endpoint (§16): `GET /logs`, a dumb full-dump endpoint with no server-side filtering/windowing (per spec's explicit decision that windowing logic belongs in `logs-mcp`, not the Target Service) - returns the currently active scenario's full pre-seeded log content, unfiltered, or an empty list if no scenario is active.

Explicitly **out of scope** for this change: real feature flags (Unleash/OFREP), real metrics (OTel/Prometheus), the `logs-mcp` server on Argus's side that would eventually consume this endpoint, any real Investigator logic reading these logs, persisting anything beyond in-memory (the log *content* lives in code, but which scenario is active is in-memory only), a UI to drive scenario selection, Slack (mimicked or real - see memory for the parked design), and the remaining five §21.1 scenario types - each substantial enough to be its own later change.

## Capabilities

### New Capabilities
- `target-service-scenario-control`: the Target Service can activate one of several pre-seeded scenarios by id, reset to no active scenario, report current status, and return the active scenario's full pre-seeded log content unfiltered.

### Modified Capabilities
(none - checked against `openspec/specs/incident-lifecycle/spec.md`, the only archived capability; `target-service-bootstrap` exists but isn't archived yet, and this change only adds new endpoints to it, changing no existing requirement)

## Impact

- `Argus-Demo-Target-App`: new scenario registry, new scenario-control endpoints, new `/logs` endpoint, in-memory "currently active scenario" state.
- No changes to `Argus` itself in this change - no `modules/*` wiring, no e2e test changes. Purely additive to the Target Service.
