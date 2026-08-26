## Why

Most of Argus is unverified on a push. CI runs lint, typecheck, the changed
modules' unit suites, and one integration suite that exercises the Anthropic
adapter in isolation. Nothing checks that the pieces work *together*: an alert
arriving at the webhook, the orchestrator's graph, the three retrieval channels
over MCP, the Argo CD adapter, persistence, and the incident reaching a
terminal status. That path is only exercised by `nox -s e2e`, which spends real
tokens and therefore runs manually, which in practice means rarely.

The evidence that this matters is recent: the last `e2e` run failed because the
Target Service container was months stale and 404'd on an endpoint the source
plainly had. Nothing else in the repo could have caught it.

Every model answer in that path can be replayed from a recording already
committed to this repo. The stack the e2e session brings up *already starts the
Anthropic double* - it simply never points the web app at it. Wiring that one
setting turns the whole pipeline into a free, keyless check that belongs on
every push.

## What Changes

- A new `e2e_replay` nox session brings up the same stack as `e2e` but starts
  `argus_web` pointed at the Anthropic double, so every model answer is
  replayed from a stored recording and no token is spent.
- `_start_service` gains an environment argument, so one service in the stack
  can be started with settings the others do not share. It has no way to do
  that today.
- The e2e tests seed the double with the recording their scenario expects,
  as an explicit `given` step beside the one that seeds the Target Service
  scenario - so a reader sees both stand-ins arranged in the same place.
- A new `e2e-replay` job in `ci.yml`, running on every push beside `lint`,
  `typecheck` and `integration`.
- `nox -s e2e` keeps talking to the real API and stays manual. The two sessions
  answer different questions and both remain worth running.
- Each of the three places a reader might land - the session docstring, the CI
  job, the test file - states plainly that this is the CI path and that every
  model answer is replayed rather than asked for.

## Capabilities

### New Capabilities
- `e2e-replay`: the end-to-end pipeline verified against recorded model
  answers, free and keyless, on every push.

### Modified Capabilities
<!-- None. This adds a way to run existing e2e tests; it changes no
     requirement about what Argus does at runtime. -->

## Impact

- `noxfile.py` - a new session, and `_start_service` gains an `env` argument.
- `.github/workflows/ci.yml` - one new job.
- `tests/e2e/` - the existing cases gain a seeding step. Human-owned
  (`AGENTS.md`), so proposed in chat rather than edited.
- `modules/anthropic_double/recordings/` - read only. The three recordings the
  existing e2e cases need are already committed.
- No production code changes. Selecting the double is a configuration value
  (`anthropic_base_url`) that already exists precisely for this.
