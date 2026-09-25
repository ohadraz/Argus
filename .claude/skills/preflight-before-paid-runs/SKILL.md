---
name: preflight-before-paid-runs
description: Use before running anything that spends money or wall-clock hours - `nox -s record`, `nox -s e2e`, `nox -s contract`, `nox -s stack`, or any run that reaches the real Anthropic API. Establishes what must be proven for free first, so a paid run fails for a reason worth paying to learn.
---

# Prove it for free before it costs money

A paid run answers exactly one question: **what does the model decide when it
reads this evidence?** Every other question it appears to answer - does the
fixture start, does the endpoint exist, does the tool get registered, does the
test's arithmetic hold - is one that could have been answered for nothing, and
answering it with a paid run means paying to learn that a file was missing from
a Docker image.

Worse for `record`: a run that dies partway still spends, and what it leaves
behind is a partial recording. A partial recording is not neutral - it is a
queue of answers that runs dry mid-incident later, and the failure it causes
reads as an agent bug in a suite nobody was thinking about.

So: **never start a paid run to find out whether it will work.** Start it only
once everything except the model's judgement has been proven.

## The rule

Before any paid or long run, work out which of its steps do *not* depend on the
model, and verify each of them directly. Anything reachable with a free tool -
a container, a curl, a unit test, a script against the fixture - gets checked
first. Report what you proved and what remains genuinely unprovable, then ask.

State the residual risk honestly. "I checked everything free" is a claim; if
the answer to "are you sure it will pass?" is no, say no and say what is still
unknown.

## What this looks like in this repo

A recording run (`nox -s "record(mode='both')" -- <name>`) touches all of this,
and only the last item needs a model:

1. **The recording has somewhere to go.** Its name exists in the e2e framework
   *and* has an entry in `scripts/record_incident.py`. A name the script does
   not know is a run that records nothing; a name nothing replays is a
   recording that cost money and answers no question.
2. **The fixture image actually carries what the code reads.** Build it and
   exercise the endpoint. `Dockerfile` copying `src/` does not copy `deploy/`,
   and the symptom is a 500 on the first request of a paid run.
3. **The scenario seeds.** `POST /scenario/seed` returns 200, not 500.
4. **The telemetry has the shape the case asserts.** Read `/metrics` from the
   running fixture and compute the assertion's own arithmetic against it. Do
   not take the numbers from an offline `generate(...)` alone: the staged
   condition is backdated by a *setting*, so how much of the window it covers
   is not what a spec paragraph implies, and a test that splits the window at a
   fixed minute count is testing the wrong minutes.
5. **Every platform call the mitigation makes.** curl the stand-in directly -
   the refusals as well as the success - and confirm the world actually changed
   afterwards.
6. **The static gates.** `lint`, `typecheck`, `guard_layering`, `guard_exports`
   over the new files, at their real paths.
7. **The composition root, driven once.** See below - this is the one the gates
   cannot do for you.
8. **The whole walk, on fabricated answers.**
   `uv run python scripts/seed_a_rehearsal.py` takes a recording set captured
   for one scenario, rewrites the answer that has to differ, and stores it under
   the new scenario's name - so `e2e_replay` drives the new case, end to end,
   before a model has been asked anything. It proves the plumbing and nothing
   about the answer, and what it writes must never be committed: the paid
   `record` run overwrites it with the real thing.
9. **Then, and only then:** what the model concludes from the evidence.

## Green gates do not prove a thing is wired

A unit test proves the tool works. A green `typecheck` proves the types agree.
Neither proves anybody *calls* it, and in this repo the collaborators are bound
with `functools.partial` at a composition root - which mypy does not check for
completeness. A partial missing a required keyword type-checks perfectly and
raises `TypeError` the first time it is called, which on a paid run is after
the money is spent.

So a new collaborator is not finished when its own tests pass. Trace it by hand
from the agent that uses it back to the process that builds it - server tool
registered, typed client function, agent-side adapter, every `partial` that
binds it, including the ones on paths the happy case never takes (a withdrawal,
an undo) - and then **drive the path once for free**: a script that calls the
real function against the running fixture, no model involved. Ten minutes, and
it is the check that would have caught this.

## Partition by the condition, not by the clock

A window's staged condition is usually backdated relative to *now*, and the
walk runs for minutes on top of that - so the affected stretch is neither a
fixed length nor a fixed fraction of the window. An assertion that slices the
last N minutes is pinned to a number that was never the point and drifts with
how long the run took.

Split on the signal that says which state each minute was in - the hit ratio,
the flag, the process start time - and compare the two populations. That
assertion says what the case actually means and survives a slow run.

## Related

- `e2e-test-placement` - which directory and marker a new case belongs in.
- `tdd-new-behavior` - how a test under `tests/` gets proposed and applied.
