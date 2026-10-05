## Context

`monitoring-blind-spot` (archived 2026-09-30) stages revision `9f4ad14`, which
renames `metrics.portName` from `metrics` to `http-metrics`, and answers it with
`RollBackDeploymentStrategy`. The scrape configuration that stops matching is
described only in comments; the outage is simulated in `state.py`
(`ScrapeOutage`) and ends only on a rollback.

Three facts decide this change's shape:

- **The gate's refusal does not stop the walk.** `NOTHING_ANSWERS_THIS_MODE`
  routes to `next_candidate` ([gating.py:370](../../../modules/orchestrator/src/orchestrator/walk/gating.py)),
  and a refused proposal records no attempt, so the next candidate is proposed.
  The paid blind-spot walk ranked `config-induced-failure` second at 0.45 on the
  same subject - a rollback. Under today's routing this scenario would end
  `mitigated` by the action it exists to decline.
- **Code-Fix cannot see `deploy/`.** `GITHUB_SOURCE_PATHS` is
  `src/io_shop,tests/io_shop` and `source_scope.belongs_to_the_service` scopes
  both retrieval channels by it. Only the unscoped file read and the deployment
  diff reach further.
- **The Investigator reads diffs, not commit messages.** Intent has to be visible
  in the diff.

## Goals / Non-Goals

**Goals:**

- A pair with `monitoring-blind-spot` that differs in the diff alone.
- A walk that names the mode, takes no action, proposes the scrape configuration
  rolled forward, and ends `escalated` with the sight still lost.
- A fix `grade_fixes` can grade.

**Non-Goals:**

- Making the simulation read the scrape configuration file. The fixture may keep
  simulating the outage; the file exists for the fix and its test.
- Any judgement of intent at the gate. The mode carries it.
- Changing `monitoring-blind-spot`'s revision pair, recordings or e2e case.
- A merged fix ending the outage. Argus never merges.

## Decisions

### A new mode rather than a refusal on the blind spot

The fault is the observer's configuration, not the deployment, and a mode is
exactly that distinction. A gate refusal ("would undo intended work") would need
a model's judgement of intent threaded into a deterministic gate.

*Alternative:* make the rollback impossible (revision gone). Rejected - a failed
action ends `escalated` without reaching Code-Fix, and it stages a different
story from a deliberate rename.

### `NOTHING_ANSWERS_THIS_MODE` ends the mitigation phase

The refusal routes to Code-Fix, as `NOTHING_COULD_CONFIRM_IT` already does, and
the walk records the fact so `status_after` derives `escalated` without reading
narration. A recommendation is not recorded - there is no action to recommend.

This is general, not shaped to the fixture: any mode nothing answers says that
no mitigation applies, and the only other such mode,
`upstream-dependency-failure`, is better served too - it currently spends every
remaining round re-reading evidence that named the cause on the first.

*Alternative:* skip only candidates sharing the refused one's subject. Rejected -
it reasons about subjects the gate has no business comparing, and leaves the
wasted rounds.

### The scrape configuration is a ServiceMonitor-shaped file under `deploy/`

`deploy/scrape.yaml` beside `values-production.yaml`, selecting by `port: metrics`.
Added to `main` in its own commit, after `9f4ad14`, so `main` carries the stale
name and the existing scenario's pair is untouched. `GITHUB_SOURCE_PATHS` gains
`deploy`; the values file becomes findable too, which is correct rather than
incidental - it is the service as deployed.

### The deliberate revision pair lives on an unmerged branch

`deploy/ports-named-for-protocol`: a parent naming two or more ports the old way,
and a tip renaming all of them to `<protocol>[-<purpose>]` with a comment stating
the convention. Unmerged, so `main` and the fix corpus stay frozen, as the
`month-*` scenarios do.

### The fix's test reads both files

The grader requires the patch's test to fail alone and pass with the fix, inside
`tests/io_shop`. The test parses both YAML files and asserts the scrape selects
the metrics port's name. It is unlike the rest of `tests/io_shop`, which tests the
package; it is the only test that can prove this fix, and the file it guards is
the service's.

### The postmortem's statement is computed

Whether the sight was restored is read from the metrics at write time - no
bucket at or after the onset - and stated by code, not by the model, under the
rule that every reported figure is computed.

## Risks / Trade-offs

- **The model may still read the convention diff as a blind spot.** → The paid
  record walk is the measurement. Under the new routing, a wrong reading ends in
  a rollback and `mitigated`, which the e2e case fails on, so it is visible.
- **The upstream recordings go stale.** A shorter walk asks the model fewer
  questions. → Confirm free first: run `e2e_replay` for that case after the
  routing change; re-record `grep-` and `both-` only if it fails. About $10.
- **New corpus costs about $5.** → Prove the walk under the double with
  hand-authored answers first.
- **Widening the scope changes tool results in every recording's walk.** The
  double replays answers in order and does not match requests, so answers stay
  valid; a model answer citing a file list may read oddly but asserts nothing.
  → Full `e2e_replay` before any recording.
- **`github_double`'s `main` lacks `deploy/`.** It is off-limits. → Propose the
  edit in chat.
