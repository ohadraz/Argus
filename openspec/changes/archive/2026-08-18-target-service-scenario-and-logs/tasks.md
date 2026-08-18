## 1. Scenario registry

- [x] 1.1 Define an in-code registry mapping scenario id to a fixed list of
  pre-seeded log entries (design.md: `SCENARIOS: dict[str, list[str]]` or
  equivalent typed structure) in `Argus-Demo-Target-App`'s `src/target_app/`
- [x] 1.2 Author the `feature-flag-toggle` scenario's log entries: a flag
  toggled on, followed by an elevated error rate (spec: "reads as a
  flag-caused error spike")
- [x] 1.3 Author the `bad-deployment` scenario's log entries: a deployment,
  followed by a latency spike (spec: "reads as a deployment-caused latency
  spike")
- [x] 1.4 Add a module-level variable holding the currently active scenario id
  (or `None`) - the only in-memory runtime state this change needs
  (design.md: "In-memory state only" decision)

## 2. Scenario control

- [x] 2.1 Implement `POST /scenario/seed`: accepts a scenario id, sets it as
  active if it exists in the registry (spec: "Seeding a known scenario id
  activates it")
- [x] 2.2 `POST /scenario/seed` with an unknown scenario id responds with an
  error status and leaves the active scenario unchanged (spec: "Seeding an
  unknown scenario id fails")
- [x] 2.3 Implement `POST /scenario/reset`: clears the active scenario back to
  none (spec: "Resetting deactivates the current scenario")
- [x] 2.4 Implement `GET /scenario/status`: reports the active scenario id, or
  none if no scenario is active

## 3. `/logs`

- [x] 3.1 Implement `GET /logs`: returns the active scenario's full pre-seeded
  log list, unfiltered, in authored order, or an empty list if no scenario is
  active (spec: "No scenario active returns no logs" / "An active scenario's
  logs are returned in full")

## 4. Verification

- [x] 4.1 Confirm every requirement in
  `specs/target-service-scenario-control/spec.md` is satisfied by manually
  walking each scenario, including switching from one active scenario to
  another and confirming `/logs` reflects the switch
- [x] 4.2 Note the in-memory-only active-scenario state (restart clears which
  scenario is active, though the pre-seeded log content itself is code and
  survives restarts) in a docstring or the README, per design.md's flagged
  risk
