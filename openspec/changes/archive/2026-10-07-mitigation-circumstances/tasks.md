## 1. Tests first (hand-applied, whole files)

- [x] 1.1 Rewrite `test_strategies.py` and `test_actions.py` to call `propose` / `propose_action` with `(hypothesis, Circumstances(...))`
- [x] 1.2 Rewrite `test_candidates.py`: `what_each_would_do(candidates, circumstances)`, plus `the_circumstances` cases (unreadable history gives `None`; absent keys and unread deployments are empty)
- [x] 1.3 Delete `test_mitigating.py`
- [x] 1.4 Confirm the suites fail for the missing names, nothing else

## 2. Implementation

- [x] 2.1 `Circumstances` in `argus_core.models`, exported from the front door
- [x] 2.2 `MitigationStrategy.propose(hypothesis, circumstances, /)` and all 8 strategies; reword docstrings that argued from the old signature
- [x] 2.3 `propose_action(hypothesis, circumstances, strategies=...)`
- [x] 2.4 Delete `mitigating.py` and its export, with `ActionTaker` and `FlagChangeFetcher` (its seams only)
- [x] 2.5 `the_circumstances` and `what_each_would_do(candidates, circumstances)` in `walk/candidates.py`
- [x] 2.6 `choosing.py`, `investigating.py`, `proposing.py` build through `the_circumstances`

## 3. Review before commit

- [x] 3.1 Comments, docstrings, jargon, docs aligned; no missing, redundant or weak tests
- [x] 3.2 lint, typecheck, guard_layering, test all, integration, full `e2e_replay(mode='both')`
- [x] 3.3 Commit (one line, approved); archive the change
