Every Argus-side item below is a TDD cycle: the test is proposed in chat, the
user pastes it, and the implementation follows it. `Argus-Demo-Target-App` is a
fixture and is covered after the fact, not before.

## 1. The clock in Argus

- [x] 1.1 `argus_core.timestamps.utc_now` reads `SIM_CLOCK_EPOCH` and
      `SIM_CLOCK_SPEED`: the real clock when neither is set, the formula when both are
- [x] 1.2 A sleep measured in the clock's seconds (`1/speed` of it real), beside
      `utc_now`, exported through `argus_core`'s front door
- [x] 1.3 `IncidentEvent.at` and the replay log's `at` default to `utc_now`
- [x] 1.4 The read tier's window end (`read_mcp_server/window.py`) reads `utc_now`
- [x] 1.5 Mitigation's waits (`take_action`'s `sleep` default) are measured in the
      clock's seconds
- [x] 1.6 The worker renews its lease `speed` times as often in real time
- [x] 1.7 Confirm no other direct read of the real clock remains in any module's
      `src/` - grep, and list what is deliberately left real (budgets, timeouts,
      idle polls). Left real: every `time.monotonic` (budgets, latency), the
      worker's idle poll, the relay's and the index loop's pauses, the write
      tier's restart and flag-propagation waits, and `orchestrator.rates`'s
      `date.today` (a local date, compared with nothing on the stack's clock)

## 2. The fixture (Argus-Demo-Target-App)

- [x] 2.1 Faked images: `postgres:16` and `unleash-server:8.1.0` plus libfaketime;
      the Target Service's Dockerfile installs it too
- [x] 2.2 The clock-writer service and its tmpfs volume in the Target Environment's
      compose file; epoch and speed default to an offset of zero
- [x] 2.3 Unleash, Unleash's Postgres (as `postgres`) and the Target Service read
      the spec file; monotonic left real
- [x] 2.4 The Target Environment still stands up on its own with nothing set, and
      its suite stays green
- [x] 2.5 Push the demo app - CI recreates the sibling checkout from GitHub. Held
      until 5.2 shows the suite green and faster
- [x] 2.6 Every image links libfaketime to `/usr/local/lib/libfaketime.so.1`, so the
      preload names one path on any architecture (an arm64 Mac included)

## 3. The stack (Argus)

- [x] 3.1 Argus's Postgres from the faked image, as `postgres`, mounting the
      included file's clock volume
- [x] 3.2 `e2e_replay` sets the epoch at the session's start and the speed to 10;
      every other session leaves both unset. `e2e` stays real: a real model's
      answer takes tens of real seconds, which at 10x ages a staged change out of
      the window Argus looks back over
- [x] 3.3 CI's e2e job gets the same, through the session rather than the workflow

## 4. The suite (the user's edits, proposed whole in chat)

- [x] 4.1 The alert builder's `startsAt` reads the shared clock
- [x] 4.2 `test_half_finished_rollout.py`'s minute waits read the shared clock
- [x] 4.3 An e2e case asserting every party's clock agrees with Argus's, the
      database clock runs at the configured speed, and the flag provider stamps
      Argus's revert inside the incident Argus's database recorded. An HTTP `Date`
      header is cached for up to a real second by Node and uvicorn alike - up to
      `speed` simulated seconds stale - so it is no measure of agreement

## 5. Verify

- [x] 5.1 `nox -s lint`, `typecheck`, `guard_layering`, `test_all`
- [x] 5.2 Full `e2e_replay(mode='both')`, backgrounded: every case green, wall clock
      compared with the last run (40/40 in 30m 35s). 43/43 in 11m 55s at 10x
- [x] 5.4 The two cases still reading the wall's clock read the stack's:
      `test_a_deliberate_rename_is_fixed_forward.py` (197s of the 11m 55s, waiting
      for the wall to catch the shop's minutes up) and
      `test_asking_who_changed_the_flag.py`; then the suite once more
- [x] 5.3 Spec §15 (or wherever the stack is specified) says the stack runs on one
      simulated clock - see the `spec-doc-style` skill
