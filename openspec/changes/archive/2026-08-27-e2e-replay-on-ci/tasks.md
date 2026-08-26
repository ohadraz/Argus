Tests are human-owned (`AGENTS.md`): every task below that needs a test means
*propose it in chat, confirm it is red, then implement*. Tasks marked
**(test)** are proposal tasks, not implementation ones. `tests/`,
`modules/argus_testkit/` and `modules/anthropic_double/` are hook-blocked -
propose the **entire file**, never a fragment.

## 1. Starting one service differently from the rest

- [x] 1.1 Give `_start_service` an optional `env` argument, merged into a copy of `os.environ` rather than replacing it - a child started with only one variable loses `PATH`, `SYSTEMROOT` and the database URL
- [x] 1.2 Extract the stack bringup shared by `e2e` and the new session into one helper both call, so the two cannot drift on everything except the one difference that matters
- [x] 1.3 Confirm by hand that `argus_web` started with `ANTHROPIC_BASE_URL` pointed at the double actually reaches it - `Settings` reads the variable already, so this is a wiring check, not a code change

## 2. The session

- [x] 2.1 Add the `e2e_replay` nox session: same stack as `e2e`, `argus_web` pointed at the double, running `tests/e2e` only
- [x] 2.2 Write its docstring per the `nox-session-style` skill, stating in the second half that **every model answer is replayed from a committed recording, no token is spent, and the model's judgement is measured by `nox -s eval`, not here**
- [x] 2.3 Add the counterpart sentence to `e2e`'s docstring - that it reaches the real API, costs money, and is the manual pre-merge run - so a reader landing on either one learns how they differ
- [x] 2.4 Verify `nox --list` shows both, and that `e2e` still behaves exactly as before

## 3. The tests

- [x] 3.1 **(test)** Propose the seeding step for `tests/e2e/framework/argus.py`: a `given` step that seeds the double with a named recording, using `repeat: null` so a widening loop cannot exhaust it
- [x] 3.2 **(test)** Propose the updated `tests/e2e/test_scenario_investigation.py`: each case names its recording beside the Target Service scenario it seeds
- [x] 3.3 **(test)** Propose the updated `tests/e2e/test_incident_lifecycle.py`, seeded with the recording that leaves the cause undetermined
- [x] 3.4 **(test)** Propose the file-level comment stating this suite runs on CI against recorded answers, and that a passing run says the pipeline works, not that the model was right
- [x] 3.5 Confirm the double is reset between cases, so one test's seed cannot answer the next test's call
- [x] 3.6 Run `nox -s e2e_replay` green, with `ANTHROPIC_API_KEY` removed from the environment - if it passes with a key present but fails without one, something still reaches the real API

## 4. CI

- [x] 4.1 Add the `e2e-replay` job to `ci.yml`, beside `lint`, `typecheck` and `integration`, running unconditionally rather than through the `detect-changes` matrix
- [x] 4.2 Comment the job with **why it is free and keyless**, and why that is what lets it run on every push - the same sentence the session docstring carries
- [x] 4.3 Confirm it does not inherit or require any Anthropic secret
- [x] 4.4 Push and confirm the job runs and passes on GitHub

## 5. Evidence and documentation

- [x] 5.1 `uv run python -m nox -s lint`, `typecheck`, `test_all`, `guard_e2e_boundary` all green
- [x] 5.2 `uv run python -m nox -s e2e_replay` green
- [x] 5.3 `uv run python -m nox -s e2e` still green against the real API - ask before running, it spends tokens
- [x] 5.4 Update `docs/spec-and-architecture.md` §18.4 (per-module CI) to describe what each suite covers and which run automatically - written as the design, not as a history of what changed
- [x] 5.5 Update `CLAUDE.md`'s "How to run things" with `e2e_replay` beside `e2e`

## 6. Follow-ups to raise, not to do here

- [x] 6.1 Raise re-recording the fixtures against demo-app-shaped evidence, so a replayed hypothesis reads coherently to someone debugging a failed e2e run
- [x] 6.2 Raise whether `nox -s contract` should run on a schedule rather than only manually - it is what catches a recording going stale, and every replay suite depends on the recordings being honest
