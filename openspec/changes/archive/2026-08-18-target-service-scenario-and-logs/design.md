## Context

`Argus-Demo-Target-App` currently exposes only `GET /health` (from `target-service-scaffold`). This design adds the smallest next slice: a small library of pre-seeded scenarios and a way to select and read one back - laying the groundwork for a later change to give the Investigator something genuine to reason about. The Target Service does not simulate live behavior; it returns pre-authored log content, one fixed set per scenario, matching what a real incident's logs would look like (spec §21.1's benchmark scenario list).

An earlier draft of this change modeled a single live-toggled endpoint (`GET /flag-gated-operation`, seeded on/off, generating log entries as it was called). That was a misreading of what was discussed and has been dropped entirely - there is no endpoint whose live request/response behavior is being simulated here, only the aftermath (logs) a real incident of that kind would have produced.

## Goals / Non-Goals

**Goals:**
- A small in-code registry mapping scenario id to a fixed list of pre-written log entries: `SCENARIOS: dict[str, list[str]]` (or an equivalent typed structure).
- Two scenarios seeded for this change, each corresponding to a distinct entry from spec §21.1's benchmark scenario list:
  - `feature-flag-toggle` (§21.1 #1): log entries reading as a feature flag being toggled on and causing an elevated error rate.
  - `bad-deployment` (§21.1 #2): log entries reading as a deployment causing a latency spike.
- Scenario control: `POST /scenario/seed` (body names a scenario id, activates it), `POST /scenario/reset` (deactivates, back to no active scenario), `GET /scenario/status` (reports the active scenario id, or none).
- `GET /logs`: returns the currently active scenario's full pre-seeded log list, unfiltered, in authored order - or an empty list if no scenario is active.

**Non-Goals:**
- Any live endpoint whose real-time behavior is simulated - this is the specific thing the earlier draft got wrong and this design removes.
- Real feature flags (Unleash/OFREP) or real metrics (OTel/Prometheus) - the scenario registry's static log content stands in for both.
- `logs-mcp` on Argus's side, or any windowing/filtering logic - `/logs` is a dumb full dump, matching spec §16's decision that filtering lives in the MCP adapter, not here.
- The remaining five §21.1 scenario types (config drift, upstream dependency failure, two simultaneous causes, ambiguous alert, Slack hint) - the registry is designed to make adding these trivial later, but only two are authored now.
- Persisting the active-scenario pointer beyond process memory - a restart clears which scenario is active (the log *content* itself is static code, not runtime state, so it's unaffected by restarts).
- Any real Investigator logic consuming this endpoint, a UI to drive scenario selection, or Slack integration (mimicked or real) - each parked as a separate later change.

## Decisions

**Pre-seeded, static log content per scenario - not live-generated.** The Target Service doesn't run any logic whose outcome is logged; it returns fixed, pre-authored text selected by which scenario is active. This directly matches what was discussed: "the demo app does nothing but ... returning pre-seeded logs, each simulating a different scenario." Alternative considered (the earlier draft): a live endpoint (`/flag-gated-operation`) whose real request/response behavior is toggled by a seeded flag and logged as it happens - rejected as a misreading of the actual design; dropped in this revision.

**`POST /scenario/seed` takes a scenario id parameter, and a registry replaces the single boolean.** Because multiple distinct scenarios are the entire point of this design (not a deferred concern), `seed` can no longer be bodyless. Reverses the earlier draft's "single seeded condition, no parameter" decision - that reasoning applied to a design with exactly one failure mode; it doesn't hold once "each simulating a different scenario" is the stated goal.

**Exactly two scenarios authored now, not all seven from §21.1.** Two is the minimum that proves the registry/selection mechanism actually generalizes (as opposed to hardcoding one case) without front-loading all of §21.1's scenario authoring into one change. Alternative considered: author all seven now for completeness - rejected, each additional scenario is just more content to write and doesn't validate anything the second one didn't already prove; the other five can be added later as flat additions to the registry.

**`/scenario/status`'s response is just the active scenario id (or none).** No separate "resolved" concept - a scenario is either active (its logs are what `/logs` returns) or not. Simpler than the earlier draft's seeded/resolved distinction, which existed to describe a live boolean toggle that no longer exists.

**In-memory state only - a module-level variable holding the currently active scenario id (or `None`).** The scenario *content* (the registry itself) lives in code, not runtime state, so it survives restarts by construction; only the "which one is currently selected" pointer is in-memory and reset by a restart. No SQLite, no file, no Postgres.

**Additive to the existing FastAPI app, not a new service or module boundary.** All new endpoints live in `target_app.app` (or a small number of new files under `src/target_app/`) alongside `/health` - this stays one deployable unit, matching `target-service-scaffold`'s existing shape.

## Risks / Trade-offs

- **[Risk]** Static, pre-authored logs may read as less realistic than logs a live endpoint would generate on the fly → **Mitigation**: accepted - that's the deliberate design now, not an oversight; realism comes from how the log content is written, not from live generation.
- **[Risk]** In-memory active-scenario state means a container restart silently clears which scenario is active (back to none) → **Mitigation**: acceptable for a demo/test fixture; worth flagging in this change's own README/docstrings so nobody's surprised by it later.
- **[Risk]** A two-scenario registry may not generalize cleanly once the remaining five §21.1 types are added → **Mitigation**: deliberately deferred rather than guessing the abstraction now; two examples already validate the id → log-list shape, and the other five are expected to be flat additions, not a redesign.

## Migration Plan

N/A - purely additive endpoints on top of the existing `target_app` FastAPI app; nothing existing changes or is removed. Rollback is deleting the new endpoints/files.

## Open Questions

- When the remaining five §21.1 scenarios are added, does the registry's value type need to grow beyond `list[str]` (e.g. structured entries with timestamps or severity levels) to support scenarios like "two simultaneous causes" cleanly? Deliberately left open until there's a concrete scenario that needs it.
- Should `POST /scenario/seed` with an unknown scenario id 404, or 400? Left for implementation to decide consistently with how the rest of the app reports client errors; not a design-level concern.
