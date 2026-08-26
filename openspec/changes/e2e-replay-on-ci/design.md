## Context

`nox -s e2e` already brings up everything this needs. It starts Postgres and
the Target Service via docker-compose, then three local processes:
`read_mcp_server`, `anthropic_double`, and `argus_web`. The double is started
*for the integration tests that run in the same session* - the noxfile says so
explicitly, and adds that "the e2e tests in the same run still talk to the real
Anthropic API - nothing points `argus_web` at the double."

That last clause is the entire gap. `Settings.anthropic_base_url` exists
precisely to select the double, and its docstring already says so: "Pointing
this at the test double is the *only* thing that selects it: the seam sits
below the SDK, so the real adapter, the real `messages.parse` and the real
schema transform still run."

So the production side needs nothing. What is missing is a way to start
`argus_web` with that setting pointed somewhere different from the rest of the
stack, and a way for a test to say which recording answers it.

## Goals / Non-Goals

**Goals**
- The pipeline from webhook to terminal incident status is checked on every
  push, free and keyless.
- One set of e2e tests serves both the replay path and the paid path.
- A reader of the session, the CI job, or the tests can tell immediately that
  answers are replayed.

**Non-Goals**
- Measuring whether the model reaches the right conclusion. The eval does that,
  against thresholds derived from 50 samples per case. A single replayed answer
  proves nothing about judgement and must not be read as if it did.
- Replacing `nox -s e2e`. It stays, it stays manual, and it stays the thing to
  run before a merge that changes the investigation path.
- Recording anything new. The three recordings the existing cases need -
  `feature-flag-toggle`, `bad-deployment`, `no-evidence` - are committed.

## Decisions

### 1. A separate session, not a flag on `e2e`

`e2e_replay` is its own nox session rather than `e2e -- --replay`.

Two sessions answering two questions is easier to reason about than one session
whose meaning depends on a posarg, and CI invokes a name rather than a name
plus an argument it must not get wrong. It also keeps the failure modes
separate: "the pipeline broke" and "the model changed its mind" should not
arrive through the same door.

The cost is duplicated stack-bringup code between the two sessions. That is
worth extracting into a helper both call, not worth avoiding by merging them.

### 2. The double is selected by environment, not by a code branch

`_start_service` gains an `env` argument. `e2e_replay` starts `argus_web` with
`ANTHROPIC_BASE_URL` set to the double's URL; every other service in the stack
starts as it does today.

`Settings` reads that variable already - it is a `pydantic-settings` field, and
nothing needs to change for it to be picked up. No production code learns that
a replay mode exists, which is the property worth protecting: a pipeline that
behaves differently when observed is not the pipeline.

`_start_service` today passes no `env` at all, so the child inherits the
session's. The new argument must *merge* into a copy of `os.environ` rather
than replace it - a child started with only one variable set would lose
`PATH`, `SYSTEMROOT`, and the database URL.

### 3. The test seeds the double, in its `given`

Each e2e case gains a step naming the recording that answers it, beside the
step that seeds the Target Service's scenario:

```
.given(
    _a_bad_version_was_deployed(),
    _the_model_answers_from(A_RECORDED_BAD_DEPLOYMENT),
)
```

The alternative - a fixture that infers the recording from the scenario name -
was rejected. It hides half the arrangement, and it ties two things together
that are only incidentally related: the recording is what the *model* said, the
scenario is what the *service* did. A test that wants a mismatched pair (a
deploy scenario where the model finds nothing) should be able to write one.

The seed step is a no-op against the paid session, where the double is running
but nothing is pointed at it. That keeps one set of tests serving both paths,
at the cost of one wasted HTTP call per case in the paid run.

### 4. Seeds use `repeat: null`

The double's queue serves one seed per call by default. The investigation loop
makes up to `investigation_max_iterations` model calls, and how many it
actually makes depends on the recorded confidence and on whether the metrics
window opened mid-incident.

Seeding with `repeat: null` - "answer every call until reset" - makes the test
independent of that count. The alternative, queueing three copies, would couple
each e2e case to the loop's current iteration budget, so raising the budget
would break tests that have nothing to do with it.

This does mean a replay run cannot assert *how many times* the model was asked.
That assertion belongs in `agent_investigator`'s unit tests, where it already
lives and where it is cheap.

### 5. The recordings' prose will not match the scenario

`bad-deployment.json` was recorded against evidence shaped like the eval
fixture - a `checkout` service, a pricing-lookup deploy - not against the demo
app's `kukibuki-service`. The double answers from what was seeded, never from
what it was asked, so the mechanics are unaffected: the adapter parses a real
Anthropic body and produces a real `Hypothesis`.

The consequence is that assertions must stay on `cause_type` and terminal
status, never on summary text or timestamps. That is already the rule the
existing e2e cases follow, and for a stronger reason - "a real model call, so
nothing here may depend on how the hypothesis is worded."

### 6. CI runs it as its own job

A fourth job in `ci.yml` beside `lint`, `typecheck` and `integration`, not a
step appended to one of them. `ubuntu-latest` ships docker compose, so no
extra setup is needed.

It runs unconditionally, not through the `detect-changes` matrix. The matrix
exists to avoid re-running a module's unit tests when nothing in that module
changed; this job's whole purpose is to catch a break *between* modules, and a
change confined to one module is exactly when that break is most likely.

## Risks / Trade-offs

**A green replay run can be mistaken for "the model works."** This is the real
risk of the change, and the reason the spec has a requirement about saying so
out loud in three places. A suite that appears to prove judgement but replays a
fixed answer would invite exactly the false confidence Argus is built to avoid
in its own hypotheses.

**Stale recordings drift silently.** A recording is a body Anthropic sent once.
If the SDK or the verdict schema moves, the replay suite keeps passing against
a shape no real server would send. This is already true of the integration
suite, and `nox -s contract` already exists to catch it - the mitigation is to
keep running it after adapter or SDK changes, not to add anything here.

**CI gets slower.** Docker-compose bringup plus three local services is roughly
a minute on top of the current run. Acceptable for what it covers; it runs in
parallel with the other jobs.

**Two sessions to keep in step.** A test added to `tests/e2e/` runs under both.
A change to the stack must be made in both. The shared bringup helper limits
this to the one difference that matters.

## Migration Plan

None. Nothing is replaced, no interface changes, and `nox -s e2e` behaves
exactly as it does today.

## Open Questions

- Should the replay job also run the `integration` suite, given it brings up
  the double anyway? Leaning no: `integration` is fast and standalone, and
  folding it in would make one job's failure ambiguous between two causes.
