## Context

Two evals are in question and they are not the same kind of thing.

The investigator eval calls the real model with fixed evidence and scores what it
concluded. It is the only thing in the repository that measures judgement, and it
is the reason `nox -s eval` is its own session: it spends a whole tool-use
investigation per sample and must never be part of `test_all`. Its thresholds sit
in `tests/framework/investigating.py`, fitted to a prompt that `db608fd` replaced
- and it fires at 50 samples, which is why the re-measure it asks for has not
been done.

Code-Fix has no eval. It proposes whole files with no sandbox and no test runner,
so it never learns whether a patch works, and neither does anybody else until a
human reads the pull request. What makes an eval possible for it at all is that
the Target Service is a real repository with a real suite, and that the corpus
already holds eight patches the model actually wrote.

One measurement shaped this design: the Target Service's suite is **286 passed, 0
failed** on `main`. The fault the flag scenario exposes is only reachable with
the flag on, and nothing covers that path. So "the failing test goes green" is
not available - there is no failing test - and a grader that only ran the suite
after applying a patch would pass a patch that changed nothing.

## Goals / Non-Goals

**Goals:**

- Make the investigator eval affordable enough to actually run after a prompt
  change, without giving up the sample count a threshold needs.
- Find out whether Code-Fix's patches work, deterministically, for free.
- Keep exactly one copy of every fact: recompute what is committed, record only
  what is not.

**Non-Goals:**

- Grading the postmortem. Its output is prose, so grading means a judge, and
  `faults_in` plus `checklist_complete` already refuse a document that is missing
  fields or quotes a figure Argus never computed. An eval there would measure the
  judge.
- Re-deriving thresholds in this change. The pool is empty; deriving from the
  first batch of 10 is the thing this design exists to prevent.
- Changing any production module. Nothing under `modules/*/src/` is touched.
- Judging whether a fix is the *right* fix in any sense beyond working. A patch
  that passes the shop's tests may still be one a human rejects, and that is a
  review, not a grader.

## Decisions

**Grade with red-then-green, not green alone.** Apply the patch's test files by
themselves first: the suite must fail. Then apply the whole patch: it must pass.
The first half is the one nobody would think to write, and it is the half that
catches the failure the tool description is already trying to prevent - a fix
submitted with a test that demonstrates nothing. Alternative considered: run only
the tests the patch touches. Rejected - it cannot see a patch that fixes one file
and breaks another, which is this job's characteristic mistake.

**The red run's failures must be the patch's own tests, by name.** "The suite
went red" is too weak a claim: a pre-existing failure anywhere would satisfy it,
and so would a test file that fails to import. So the red run's failing node IDs
SHALL be exactly ones belonging to the patch's test files, and those same node
IDs SHALL pass once the whole patch is applied. What remains after this is a test
inside the patch that fails for a reason unrelated to the fault and then passes -
much narrower, and not reachable by a grader that never reads the code.

**The grader lives under `tests/eval/`, not in `scripts/`.** It was drafted as a
script on the reasoning that it spends nothing and therefore does not belong in
a token-spending session. That reasoning loses to a stronger one: the patches it
grades were produced by a prompt Claude wrote, so a grader Claude also wrote is
Claude grading its own work - which is the whole reason `tests/` is off-limits to
it. It is proposed in chat and applied by a human, like every other test here.
The draft at `scripts/grade_recorded_fixes.py` is discarded rather than
committed.

**Grading writes into the Target Service's tree and restores it with version
control.** Alternatives considered: a temporary clone, rejected because the
shop's virtual environment is what runs its suite and a clone has none; copying
the tree, rejected because the installed package points at the original `src/`,
so the copy would be tested against the real source. Writing in place is the only
approach that tests what the patch says. The safeguard is a refusal: a dirty tree
there stops the run before anything is written.

**Restoration uses `clean -fd`, never `-fdx`.** The virtual environment is
ignored by version control, and `-x` would delete the interpreter the next suite
run needs.

**Ten samples per case stays; a batch covers fewer cases.** The 50 is five cases
at ten apiece, and ten is already the floor worth having: at 5 a 95% interval is
roughly ±40 points, which distinguishes nothing short of total failure, where at
10 it is near ±25 and catches a real regression. So the cut is in cases per run,
not samples per case - one case is ten walks. Twenty samples is the depth worth
acting on a difference at and fifty the depth worth re-deriving a threshold at,
both reached by running again rather than by paying once.

**The eval's pinned budget is re-synced to the configured one.** It restates
`MAX_TOOL_CALLS`, `MAX_TOKENS` and `MAX_SECONDS` deliberately, so that changing
a bound shows up in review beside the thresholds it invalidates - and it drifted
anyway: 150,000 tokens against a configured 200,000. Every score on record was
taken under a tighter bound than production gives the model. Re-syncing is
itself a change that invalidates thresholds, though in the lenient direction.

**A batch compares against the threshold; only the pool re-derives it.** These
are different questions and conflating them is how a threshold fitted to ten
samples acquires the authority of fifty.

**A prompt change starts a new pool.** Rows carry the commit, and samples taken
before a change to the brief, a tool description or a budget are not pooled with
samples taken after it. Without this the file accumulates a pass rate for a
prompt that no longer exists - exactly the failure this change is fixing.

## Risks / Trade-offs

- **The shop's suite takes about 60 seconds, and grading runs it twice per
  patch** → the red half runs with `-x`, so it stops at the first failure; only
  the green half runs to completion. Eight patches is minutes, not hours, and it
  is free, so it backgrounds.

- **The model writes its own test, so red-then-green could be satisfied by a
  failure that has nothing to do with the fault** → narrowed by naming: the red
  run's failing node IDs must belong to the patch's test files, and must be the
  ones that pass afterwards. That removes a pre-existing failure elsewhere and a
  test file that merely fails to import. What remains - a test inside the patch
  failing for an unrelated reason, then passing - is accepted and stated, because
  telling it apart means reading the code, which is a review.

- **Grading writes into another repository's working tree** → refused outright
  when that tree is dirty, and restored in a `finally`. Still the riskiest thing
  here, and the reason the refusal is a requirement rather than a courtesy.

- **A pooled results file invites pooling across a prompt change by accident** →
  each row carries the commit, and the pool is defined as samples since the last
  prompt change. The weakness is that "the last prompt change" has to be known;
  it is read from the history of the files the eval names, not asserted by hand.

- **Ten samples will sometimes pass a prompt that a fuller pool would fail** →
  accepted deliberately. The alternative on offer is not fifty samples; it is
  zero, which is where this has sat since `db608fd`.

## Migration Plan

1. Land the grader and its nox session. It is free, so it can run immediately and
   its verdict on the current corpus is knowable before anything else changes.
2. Reduce the investigator eval's sample count and add the results file, empty.
3. Run one paid batch of 10. Append it. Compare against the existing thresholds
   as a regression check, and do not touch them.
4. Leave the thresholds alone until the pool reaches the declared depth.

Rollback is per step and needs nothing: the grader is additive, and the sample
count is one number.

## Open Questions

- What pool depth licenses re-deriving a threshold - 20 or 50? The design assumes
  the eval declares it rather than leaving it to judgement, but the figure itself
  is not settled here.
- Where the results file lives, and whether one file serves every eval or one per
  eval. One file is simpler to read; one per eval is simpler to pool correctly.
- How "the last prompt change" is determined in practice: the commit touching the
  brief and tool descriptions is unambiguous today, but a change that only alters
  a budget is easy to miss.
