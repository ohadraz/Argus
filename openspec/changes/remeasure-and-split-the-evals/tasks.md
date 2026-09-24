## 1. The mechanical grader

- [x] 1.1 Delete the draft at `scripts/grade_recorded_fixes.py` - it is in the wrong place and Claude may not own it
- [x] 1.2 Propose the grader in chat as a whole file under `tests/eval/`, for a human to apply
- [x] 1.3 Refuse to run when the Target Service's tree is dirty, and say so rather than writing anything
- [x] 1.4 Read each scenario's patch from its corpus, tolerating a `files` argument that arrived as JSON text
- [x] 1.5 Grade red-then-green: the patch's test files alone must fail the suite, the whole patch must pass it
- [x] 1.6 Require the red run's failing node IDs to belong to the patch's own test files, and to be the ones that pass afterwards
- [x] 1.7 Restore the Target Service in a `finally`, with `clean -fd` and never `-fdx`
- [x] 1.8 Report a walk that proposed no fix as having nothing to grade, not as a failure
- [x] 1.9 Name which patch fell short and why, so a failure says what a reader has to go and look at

## 2. Running it

- [x] 2.1 Decide how it is run given that it costs nothing but lives in `tests/eval/`, whose session is defined as the one that spends tokens
- [x] 2.2 Decide whether it joins pre-commit or stays manual, and follow `pre-commit-hook-style` if it joins
- [x] 2.3 Run it against the current `both` corpus and record what the eight recorded patches are actually worth

## 3. The investigator eval's batching

- [x] 3.1 Establish what the 50 actually is - five cases at ten samples each, so the per-case count is already ten and is not what to cut
- [x] 3.2 Say in the eval itself that a batch detects a regression and does not re-derive a threshold
- [x] 3.3 Leave every existing threshold untouched in this change
- [x] 3.4 Make a run over a subset of cases a first-class thing rather than an accident of `-k`
- [x] 3.5 Re-sync the eval's pinned budget: it measures at `MAX_TOKENS = 150_000` while `investigation_max_tokens` is 200,000

## 4. Pooling paid samples

- [x] 4.1 Decide where the results file lives and whether one file serves every eval (open question in the design)
- [x] 4.2 Append one row per sample - date, commit, case, outcome - and never rewrite a row
- [x] 4.3 Compute the pass rate over every sample since the last prompt change, not over the latest batch
- [x] 4.4 Declare the pool depth that licenses re-deriving a threshold, and refuse to derive below it
- [x] 4.5 Record alongside any derived threshold how many samples it rested on

## 5. Proving it before it is paid for

- [x] 5.1 Run the grader on the current corpus - it is free, so its verdict is known before any paid step
- [ ] 5.2 Follow `preflight-before-paid-runs`: everything but the model's judgement proven free first
- [ ] 5.3 Run one batch of 10 against the real API and append it
- [ ] 5.4 Compare that batch against the existing thresholds as a regression check, and change nothing on the strength of it

## 6. Tests

- [x] 6.1 Propose every file under `tests/eval/` in chat as a whole file - the grader included, since it is the thing that judges Claude's own work
- [x] 6.2 Not applicable: `pooling.py` is test-support, and this workspace does not unit-test test-support - `argus_testkit` has no suite and is excluded from discovery
- [x] 6.3 Keep the grader verifiable by running it against the committed corpus, whose verdict a human can check by hand

## 7. Writing it down

- [x] 7.1 Update `docs/spec-and-architecture.md` where it describes the evals, following `spec-doc-style`
- [x] 7.2 Note in `CLAUDE.md` that the grader session exists and what it costs (nothing)
- [ ] 7.3 Archive this change as a separate commit from its implementation
