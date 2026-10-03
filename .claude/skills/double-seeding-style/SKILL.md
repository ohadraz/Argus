---
name: double-seeding-style
description: Use when a test double needs to know something specific - a commit sha, a message, a canned response, a scenario's own data - or when adding state to `github_double`, `anthropic_double` or `slack_double`. Covers why that knowledge belongs to the test that needs it rather than to the double, and the `/double-control/*` seam it travels through.
---

**A double knows how its vendor behaves. It never knows what a scenario
contains.** Those are different kinds of knowledge and only the first one is the
double's. A double that holds the second is a second fixture, kept in a file
nobody edits when the scenario changes.

So the default, whenever a double has to answer with something particular:

- the double exposes a `POST /double-control/<verb>` endpoint that takes the
  particular thing and remembers it
- the case that needs it stages it in its `given`, beside the scenario it
  belongs to
- the double itself names nothing, and its code reads the same whichever
  scenario is running

## Why, from the one that was done the other way

`github_double` once held two real commit shas of the Target Service, staged
into every `reset()`, because a scenario's deployment history named them and a
comparison between commits the double had never heard of answered 404. It
worked, and three things were wrong with it.

It was a copy. The shas were already in the demo app's `scenarios.py`, which is
where the scenario chose them, so the same fact lived in two repositories with
nothing keeping them equal.

It was a copy that only covered one scenario. The next scenario to name two real
commits would 404 exactly as the first one had, and the comment left behind -
"the alternative was a comparison that 404s on every run, which is what this
replaces" - read as though the problem were solved in general.

And it made the double's behaviour depend on which scenario you were in, while
reading as though it did not. Every case paid for two staged commits it had no
use for.

The fix was a `POST /double-control/stage-commit` taking a sha and its files,
called by the one e2e case whose diagnosis is the diff between those commits.
The double went back to knowing only how GitHub answers.

## What stays in the double

Vendor behaviour, in full. Status codes, wire shapes, the refusals the real
service makes - `BranchAlreadyExists` as a 422, an unknown ref as a 404, a
counter that climbs and never reuses a number. A double that softens one of
those stops being evidence.

Its own identity as a stand-in, where the vendor's API has no way to tell it.
Prefer echoing the request: `github_double` builds a pull request's address from
the `owner` and `repo` the caller named rather than holding either.

A bulk fixture that is the same for every case can stay, if it is *generated*
rather than written. `github_double/fixture/` holds the Target Service's source
because that is the repository's contents, identical whatever is staged, and
`scripts/snapshot_the_shop.py` refreshes it. Hand-written would be a different
answer.

## Shape of the endpoint

Match the ones already there - `reset`, `seed`, `pulls`, `branches`. A POST that
takes JSON and answers with a small object, no cleverness:

```python
@app.post("/double-control/stage-commit")
async def stage_a_commit(request: Request) -> JSONResponse:
    asked: dict[str, Any] = await request.json()

    repository.stage_commit(asked["sha"], asked["files"])

    return JSONResponse({"status": "staged", "sha": asked["sha"]})
```

Whatever it stages must be cleared by `reset()`, which suites call between
cases. State that outlives a case is how the second test in a file fails for the
first one's reasons.

## Shape of the staging, in the case

A step in `given`, named for what it arranged, returning the callable so the
work happens when the case runs rather than when it is assembled - the same
shape as `a_scenario_was_seeded`:

```python
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_SHOP_THAT_STOPPED_REPORTING)),
            calling(the_model_answers_from(RECORDED_MONITORING_BLIND_SPOT)),
            calling(_the_deployment_history_was_staged())
        ) \
```

The particulars - the shas, the file, its two versions - are constants at the
top of that case's own file, with a comment saying why this case is the one that
knows them. A helper used by one case stays in that case's file; lift it to
`tests/e2e/framework/` only when a second case needs it.

## Reminder

Every double is off-limits to Claude - `anthropic_double`, `slack_double`,
`github_double` - as is everything under `tests/`. Both halves of this pattern
are therefore proposed in chat for the user to paste, which means both halves
want exact addresses: see the `hand-apply-edit-format` skill.
