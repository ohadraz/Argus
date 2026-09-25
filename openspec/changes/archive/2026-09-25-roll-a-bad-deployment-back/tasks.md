## 1. The rename, alone and green

- [x] 1.1 Rename in `argus_core`: `ROLL_BACK_CONFIGURATION` → `ROLL_BACK_DEPLOYMENT`,
      `RollBackConfiguration` → `RollBackDeployment`, `ConfigRollbackUndo` →
      `DeploymentRollbackUndo`, and the `models/__init__.py` export list
- [x] 1.2 Rename in the write tier: the tool `roll_back_configuration` →
      `roll_back_deployment` in `write_mcp_server` (server registration and
      `rolling_back.py`) and the typed function in `write_mcp_client`
- [x] 1.3 Rename in `agent_mitigation`: `RollBackConfigurationStrategy`,
      `tools.py`'s protocol and named functions, `trying.py`'s match arms,
      `undoing.py`, and `admitting.py`'s member of `GENERIC_MITIGATIONS`
- [x] 1.4 Rename in `agent_investigator` (`investigation.py`) and
      `argus_narration`, and correct the narrated sentence so it says the
      deployment was returned to the revision it ran before
- [x] 1.5 Rewrite the prose a substitution cannot: the docstrings in
      `rolling_back.py`, `strategies.py`, `tools.py` and `undoing.py` that argue
      from "configuration", and `failure_mode.py`'s module docstring and
      `CONFIG_INDUCED_FAILURE` comment, which argue from the criterion this
      change drops
- [x] 1.6 Nothing to migrate: revision `001` stores `action_type` and the undo
      `kind` as free text with no enum, check or default naming either value, so
      the rename touches no DDL and needs no schema run
- [x] 1.7 **Human step**: apply the identifier rename to the fourteen test files
      with the single command in `design.md`; Claude may not edit them
- [x] 1.8 `nox -s lint`, `typecheck`, `guard_layering`, `guard_exports`,
      `guard_written_columns` and `test_all` green - this is the evidence the
      rename changed nothing
- [x] 1.9 Committed as two: the rename (`f9b20c1`) and the criterion with the
      two model-facing mode meanings it changed (`179152e`), which is a prompt
      change and does not belong under a refactor

## 2. The Target Service's slow revision (demo repo, code first)

- [x] 2.1 In `Argus-Demo-Target-App`, make `average_spend_per_item` recompute the
      total from the purchases once per purchase - same figure, quadratic cost,
      on the always-on path. Not the typical-spend guard, which would make the
      monthly summary unreachable and disarm three flag scenarios
- [x] 2.2 Committed as `5e07d73148d0a704b8fefe5f379bc652bb773655`, whose parent is
      `70dbcfde2b549d110a3817d92d60b6dd9786e78b` - the pair the scenario names
- [x] 2.3 Cover the unguarded path in the demo app's own suite, after the code, as
      that repo's policy has it

## 3. The scenario becomes live (demo repo)

- [x] 3.1 Replace `bad-deployment`'s authored minutes with a generated scenario:
      a `deploy_is_slow` flag on `Scenario`, `ScenarioDeploy` naming the commit
      from 2.2, and the parent as the entry before it in the revision history
- [x] 3.2 Generated from which revision is deployed, at a tenfold multiplier on the
      baseline quantiles: measured 45->460 (p50), 213->2060 (p95), 370->3730 (p99),
      error rate flat, heap flat, pages correct. No timeouts - nothing fails, and
      an error rate that moved would make it a different incident
- [x] 3.3 Keep the deploy out of the logs - no line naming a deployment, version
      or release, so the deploy history is the only evidence of a cause
- [x] 3.4 Renamed to `roll_the_deployment_back()` and generalised: it ends the
      cache outage or the slow-revision stretch, whichever the deployed revision
      caused; both refusals on the rollback endpoint are untouched
- [x] 3.5 Demo-app tests for the generated window and the rollback hook; its full
      suite green
- [x] 3.6 Committed as `b4fba1a` and pushed with `5e07d73`, so both revisions the
      history names are fetchable from GitHub

## 4. Argus answers the mode (TDD - each test proposed in chat first)

- [x] 4.1 Registered in `DEFAULT_STRATEGIES`. Two existing tests used this mode
      as their example of one nothing answers and now name
      `UPSTREAM_DEPENDENCY_FAILURE`, which is unanswered by design
- [x] 4.2 Propose the test that the gate admits it without approval, and confirm
      `GENERIC_MITIGATIONS` needs no change - membership is by kind, and the
      kind is already in the set
- [x] 4.3 Already covered, and mode-blind by construction: the undo dispatches on
      the descriptor kind, so a rollback from a bad deployment and one from a
      broken value are the same descriptor. The revision, the resumed
      reconciliation and the application nobody was reconciling are pinned in
      `write_mcp_server`'s own suite
- [x] 4.4 Already covered: narration renders from the action tag, and the words
      the rename corrected - "Rolled back the deployment of", "rolling X back" -
      say nothing about which mode led there
- [x] 4.5 `test_all` and `integration` green - 1333 and 8

## 5. The walk, rehearsed free

- [x] 5.1 Written as two cases, because an unwind only runs while the run is
      still claimed - so the withdrawal has to land mid-walk and cannot follow a
      walk that reached `mitigated`. `test_a_bad_deployment_is_rolled_back.py`
      carries the first; `test_withdrawing_an_incident.py` gains the second. The
      escalation case it supersedes is gone, and the rollback assertion the two
      rollback cases share is lifted into the e2e framework
- [x] 5.2 No new name: both cases replay `bad-deployment`, as the flag
      withdrawal case replays the flag toggle. What changed is what that
      recording is of - a walk that mitigates, not one that stopped at a
      judgement
- [x] 5.3 Green first time: 4 of 4 under `e2e_replay(mode='both')` in 89s, on a
      set borrowed from `both-cache-misconfigured` - the same world, the same
      action, and no answer that had to differ. The script now takes `--from`
      and `--as`, refuses a borrow across modes, and rewrites an answer only
      where a set says one has to. The real recordings are back in the tree.
      `grep` cannot be rehearsed: nothing under that prefix rolls anything back
- [x] 5.4 The green rehearsal is the checklist: it seeded the scenario, split
      `/metrics` by the condition and did the assertion's own arithmetic against
      the live window, and drove every platform call the mitigation and the
      withdrawal make - including the composition root's bindings on the undo
      path, which no gate checks. Gates green at their real paths: `lint`,
      `typecheck`, `guard_layering`, `guard_exports`, `guard_e2e_boundary`

## 6. The paid run

- [x] 6.1 Live as a mode and dead as a corpus: `meaning` is in
      `_CODE_SEARCH_MODES`, but nothing under that prefix records the cache, the
      leak or the canary, so `e2e_replay(mode='meaning')` cannot pass and no
      session replays its 16 `bad-deployment` answers. It does not re-record
- [x] 6.2 Both captured, 1 of 1 each: `both` in 7 minutes and 11 answers (was
      4), `grep` in 6 and 8 (was 17, and the nine stale extras were discarded as
      answers of a walk this run did not need). The real model named the
      revision and the minute it landed in both modes, rolled back, confirmed
      recovery and ended `mitigated`. No new case name to record - both e2e
      cases replay this one
- [x] 6.3 Summed from the recordings rather than the replay log, which the
      teardown takes with it: 44,418 output, 129,070 cache-write, 290,531
      cache-read, 38 input across the two runs - on the order of a dollar
- [x] 6.4 `both` green, 25 of 25. `grep` failed two cases whose recordings had
      never been captured under that mode - `git log --diff-filter=A --all`
      finds no commit that ever added them, so the mode has been red since each
      case was written. Both recorded (2 of 2, 10 minutes) and both now pass
- [x] 6.5 A recorded answer can name an absolute window, and the world it is
      replayed against is seeded fresh - so the first `both` run failed on the
      change channel answering correctly with nothing. Fixed by rebasing at the
      seam that arms the double: the Target Service now reports `seeded_at`, a
      recording run writes that instant beside the set it captures, and
      `the_model_answers_from` shifts the window bounds in each answer by the
      gap between the two seedings. Window arguments only - rewriting the prose
      would make the stored answer something Anthropic never returned. The two
      sets captured before anchors existed were given one by hand, derived from
      the deploy each quotes and accurate to under a minute against a
      five-minute margin

## 7. What the system says about itself

- [x] 7.1 Spec §7.3, §12.1, §13, §15.3 and §21.1: the action named for the
      deployment, the mapping stated as many-to-one, the write tier's two tools
      renamed, the scenario row rewritten for what it now stages, and the
      "nothing in the set answers a bad deployment" claim moved to the upstream
      outage, which is the cause that now holds it
- [x] 7.2 `docs/failure-modes-backlog.md`: change-induced reads built, the
      paragraph about what FM-09 waited for is gone, and FM-09 has a section of
      its own beside FM-10 saying why one action answers both
- [x] 7.3 `openspec/specs/` synced, and the spec folder
      `config-rollback-mitigation` renamed to `deployment-rollback-mitigation`
      at archive time
