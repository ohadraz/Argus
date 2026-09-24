## Why

The investigator eval's thresholds were fitted to a prompt that no longer
exists. `db608fd` changed the standing brief, a tool description and the read
budget in one commit - the three things the eval itself names as requiring a
re-measure - so every threshold it gates on is now justified by nothing. Left
alone it will keep passing, which is worse than failing: a green gate measured
against a vanished prompt reads as evidence and is not.

Re-measuring is currently one indivisible act of 50 full Opus-5 investigations -
five cases at ten samples apiece. That price is why it has not been paid, and it
does not have to be paid at once: samples are independent, so one case now and
another later answer the same question as all five together, provided the results
are kept.

Meanwhile the agent that spends the most and is the only one that writes to a
branch a human may merge has no eval at all. Code-Fix runs statically - no
sandbox, no test runner - so it never learns whether the patch it proposed
works. Nobody else finds out either.

## What Changes

- A run of the investigator eval may cover **a subset of its cases**, pooled
  across runs, rather than all five every time. The 50 investigations are five
  cases at ten samples each - the per-case count is already ten and is not the
  thing to cut, since below that a batch distinguishes nothing. One case is ten
  walks, which is an affordable batch.
- The eval's pinned budget is **re-synced to the configured one**. It measures
  under `MAX_TOKENS = 150_000` while `investigation_max_tokens` is 200,000, so
  it has been scoring the model under a tighter bound than production gives it -
  the drift its own comment exists to prevent.
- Paid eval samples are **written to a committed append-only results file** -
  one row per sample. They are not reproducible, so a sample discarded is a
  sample paid for twice.
- Code-Fix gets an eval, and it is **mechanical rather than a judge**: apply a
  recorded patch's test files alone and the Target Service's suite must go
  **red**; apply the whole patch and it must go **green**. No model call, no
  threshold, no prose to grade.
- That grader **spends nothing**, because it grades patches already captured in
  the committed corpus, and so it **writes no results file**.
- The red run is checked **by name**: the tests that failed must be the patch's
  own, and must be the ones that pass afterwards. Otherwise a pre-existing
  failure, or a test file that will not import, would read as proof.
- The grader lives under `tests/eval/` and is **proposed rather than written by
  Claude**, like every other test here. The patches it grades came from a prompt
  Claude wrote; a grader Claude also wrote would be marking its own work.
- The postmortem gets **no eval**. Its output is prose, so grading means a
  judge; what already protects it is deterministic and belongs where it is.

## Capabilities

### New Capabilities
- `fix-grading`: whether a recorded Code-Fix patch actually works, decided by
  running the Target Service's own tests twice - once with the patch's tests
  alone, once with the whole patch - and what each outcome means.
- `eval-sampling`: how many samples an eval run takes, how runs pool into one
  population, which results are written down and which are recomputed from
  what is already committed.

### Modified Capabilities

None. No existing spec states how the evals are sampled or scored; the
thresholds live in `tests/eval/test_investigator_eval.py` and
`tests/framework/investigating.py` alone, which is part of the problem this
change is addressing.

## Impact

- `tests/eval/` - the investigator eval's sample count and its recording of
  outcomes; a new eval for Code-Fix.
- `noxfile.py` - how a grader that costs nothing is run, given that the session
  holding it is defined as the one that spends tokens on every run.
- A committed results file for paid samples; nothing committed for the grader.
- `Argus-Demo-Target-App` is read and written during grading, and restored from
  git afterwards. Grading refuses to run against a dirty tree there.
- No production module changes. Nothing under `modules/*/src/` is touched by
  this change.
