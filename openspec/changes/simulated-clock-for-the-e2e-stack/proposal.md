## Why

Most of the e2e suite's wall clock is waiting on minutes - for the next whole
minute, for the clear minutes a recovery has to show, between metric reads. The
backlog's "flap with no rhythm is reported mitigated" defect can only be fixed by
watching longer after a confirmation, which on a real clock lengthens every
mitigation case. A stack whose minutes are simulated pays seconds for them, so the
fix stops costing the suite anything and the suite gets faster as it is.

## What Changes

- One simulated clock for every process of an e2e stack: simulated time is
  `epoch + (real - epoch) * speed`, both values handed to the stack by nox.
  Unset, every clock is the real one and nothing behaves differently.
- Argus reads it through `argus_core`: `utc_now`, and a sleep measured in
  simulated seconds. Every direct read of the real clock in Argus's runtime path
  goes through it - event and replay-log stamps, the read tier's window end,
  Mitigation's waits, and the worker's lease renewal, whose lease Postgres measures
  on the simulated clock.
- The parties that cannot run Argus's code follow the same clock through
  libfaketime: Argus's Postgres, Unleash, Unleash's Postgres and the Target
  Service. A clock-writer service in the stack rewrites libfaketime's spec on a
  shared in-memory volume every 100ms, so every container reads one offset rather
  than anchoring a speed to its own start.
- Both Postgres images start as `postgres` rather than root: libfaketime hangs the
  official entrypoint's switch from root.
- `e2e_replay` runs at a speed above 1; every other session runs at 1. `e2e`
  stays real: a real model's answer takes tens of real seconds, which at 10x
  ages a staged change out of the window Argus looks back over.
- The e2e framework reads the same clock where it reads one (the alert's
  `startsAt`, the minute waits in `test_half_finished_rollout.py`). Those are the
  user's edits.

## Capabilities

### New Capabilities
- `simulated-clock`: one clock shared by every process of a stack, running at a
  configured multiple of real time, and the guarantee that the parties agree on it.

### Modified Capabilities

## Impact

- `argus_core.timestamps`, `argus_core.events`, `argus_core.replay`,
  `read_mcp_server.window`, `agent_mitigation.trying`, `orchestrator.worker`.
- `docker-compose.yml` (Argus) and the Target Environment's compose file and
  Dockerfile in `Argus-Demo-Target-App` - a separate repo, committed separately.
- `noxfile.py`: the epoch and speed for the e2e sessions.
- No new recordings: replay was proven on the existing ones, unchanged.
- Measured in a throwaway worktree: the refuted flag case ran 20.1s at 10x against
  121.1s at 1x, every clock within 1.7 simulated seconds of the others.
