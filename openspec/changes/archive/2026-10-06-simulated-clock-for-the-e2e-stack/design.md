## Context

An e2e stack is five kinds of process that each read a clock: Argus's host
processes (Windows, macOS or Linux), Argus's Postgres, Unleash (Node), Unleash's
Postgres, and the Target Service (Python, in a container). The minutes they measure
are the Target Service's generated minutes, so nearly every wait in the suite is a
wait for a minute to pass. Today all five read the real clock, and a case that
waits out a verification window pays it in full.

A throwaway worktree proved the shape below end to end: the refuted flag case
passed at 10x in 20.1s against 121.1s at 1x, on the existing recordings, with all
five clocks within 1.7 simulated seconds of each other.

## Goals / Non-Goals

**Goals:**
- One clock for the whole stack, at a configured multiple of real time.
- No behaviour change at speed 1, which is every session but `e2e` and `e2e_replay`.
- No new recordings.

**Non-Goals:**
- A stepped or frozen clock. Time keeps flowing; only its rate changes.
- Speeding up real work - model calls, HTTP, window builds stay what they cost.
- The flap fix itself. That is the next change, and this one is what makes it free.

## Decisions

**A formula, not a clock server.** Simulated time is
`epoch + (real - epoch) * speed`, with both numbers handed to every process at
start. Each process computes the same instant from its own real clock with no
round trip, and no process can be ahead of a server it has not asked yet.
Alternative considered: a clock service every process queries - a network hop on
every `now()`, and a single point the whole stack stalls on.

**Read from the environment in `argus_core.timestamps`, not from `Settings`.**
The clock is read by pydantic default factories at import time and by the pytest
process, and `timestamps` is the one module everything already imports for it.
Routing it through `Settings` would make the kernel's lowest module depend on its
configuration layer. Names are `SIM_CLOCK_EPOCH` and `SIM_CLOCK_SPEED` - neutral,
because the Target Environment reads them too and its compose file never names Argus.

**Two kinds of wait, and only one is scaled.** A wait standing for time passing
in the world being watched - Mitigation's re-reads and arrival polls - is measured
in simulated seconds. A wait bounding real work - an HTTP timeout, the
investigation budget, the worker's idle poll - stays real. The worker's lease
renewal is the one awkward case: its lease is measured by Postgres, which is on the
simulated clock, so its renewal interval is scaled to match.

**libfaketime for every party that cannot run Argus's code, fed by a file.**
The third parties (Postgres, Unleash) and the Target Service follow the clock
through libfaketime. Its `FAKETIME="@start xK"` form was measured and rejected:
it anchors the speed to each process's own start, so containers came up 11-23
simulated seconds apart at 60x. Instead a clock-writer service rewrites a
relative offset (`+N`, where `N = (real - epoch) * (speed - 1)`) into a spec file
on a shared tmpfs volume every 100ms; every faked process reads that one file
(`FAKETIME_TIMESTAMP_FILE`, `FAKETIME_NO_CACHE=1`). Proven live: a running
Postgres follows each rewrite with no restart.

**No speed factor in libfaketime, and monotonic left alone.** Only the wall clock
is shifted (`FAKETIME_DONT_FAKE_MONOTONIC=1`). Timers, timeouts and sleeps inside
the containers stay real, so Unleash's scheduler, Postgres's checkpoints and the
Target Service's HTTP timeouts behave exactly as they do today.

**The Target Service by libfaketime, not by code.** It is a fixture; a seam
threaded through its thirty-odd clock reads buys nothing libfaketime does not
already give, and it is the same mechanism as the third parties beside it.

**Postgres starts as `postgres`.** The official entrypoint starts as root and
switches with `gosu`; under libfaketime that switch hangs with no output (measured).
Starting as `postgres` skips the switch and initialises normally.

**Where the pieces live.** The clock writer, its volume, and the faked Unleash,
Unleash database and Target Service belong to the Target Environment's compose
file, which must still stand up on its own: there the epoch and speed default to
an offset of zero. Argus's compose file fakes only its own Postgres and mounts the
volume the included file declares (proven: one volume, shared). The faked images
are small Dockerfiles - `postgres:16` and `unleash-server:8.1.0` plus the distro's
libfaketime package.

**Speed 10, and for `e2e_replay` alone.** Real work costs `speed` times as much
simulated time: a 1.3s window build is 13 simulated seconds at 10x and 78 at 60x,
against a ten-second re-read interval. 10 is what was proven; it is one setting in
the noxfile. The paid `e2e` stays real for the same reason taken further: a real
model answers in tens of real seconds, so an investigation of a few real minutes
is most of an hour at 10x, and a staged change falls out of the hour Argus looks
back over.

**One library path on every architecture.** Debian files libfaketime under the
machine's triplet, and a preload naming a path that is not there is ignored with a
warning - so an arm64 Mac would run on the real clock with nothing said. Every
image links the library to `/usr/local/lib/libfaketime.so.1`, and that is what is
preloaded.

## Risks / Trade-offs

- [The host's clock and Docker's VM clock drift apart, and drift is multiplied by
  the speed] → measured within 1.7s at 10x; the e2e case asserting agreement
  catches it on every run.
- [A future direct `datetime.now()` in Argus silently reads real time] → the
  agreement case only sees the paths it walks. A lint ban on the real clock
  outside `timestamps.py` would close it - see Open Questions.
- [Real work is inflated in simulated time, so a slow build reads as minutes of
  silence] → speed kept at 10; the agreement case would show a stack too slow for it.
- [libfaketime's per-call file read costs throughput] → tmpfs, local to the VM;
  not measurable in the proven run.
- [The test process reads the real clock in a few places] → the alert's
  `startsAt` and `test_half_finished_rollout.py`'s minute waits move to the shared
  clock; those are the user's edits. Test timeouts stay real and only get more
  generous.

## Open Questions

- A ruff `banned-api` (TID251) rule for `datetime.now` and `time.time` outside
  `argus_core.timestamps`? It adds a rule set to the root `pyproject.toml`, which is
  the user's call.
