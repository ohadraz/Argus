## 1. The shop drifts from a deployment

- [x] 1.1 Two commits on a branch of their own in `Argus-Demo-Target-App`, never
      merged: the parent, and one that drops the monthly addition with no flag
      consulted. **Push** before anything reads them. Branch
      `deploy/month-derived-from-history`: `4c810f2` (main's head) -> `26f1d7e`
- [x] 1.2 The scenario: `drifts_the_monthly_total` plus a `ScenarioDeploy` of that
      revision, its hash constants commented as the control-plane pair's are, and
      a description saying Code-Fix reads main, where the same fault sits behind
      the flag
- [x] 1.3 `state.py`: backdate the deploy entry to the drift's onset, and backdate
      no flag history where a deploy carries the drift
- [x] 1.4 The platform stand-in's rollback stops the drift and repairs nothing
- [x] 1.5 Harness tests: deploy history holds the revision at the onset, flag
      history empty, window flat, check finds the drift, rollback stops it and
      repairs nothing, restart changes nothing. `tests/io_shop` still green -
      603 passed
- [x] 1.6 Console entry under foundational integrity - offered by default; a
      test says so

## 2. The deploy history reaches Mitigation

- [x] 2.1 `fetch_recent_deployments` in `agent_mitigation.tools`, shaped like
      `fetch_recent_flag_changes`: lookback, `onset` anchor. Argus's own
      rollbacks are not dropped - the one reader is a mode whose action is
      never taken. `deployments_over` binds it to the read tier
- [x] 2.2 Read it in `investigator_node` beside the flag history; unreadable is
      `None`, published as an unanswered retrieval. The collaborator defaults to
      absent, carried as `None`, so the node's 63 existing cases are untouched
- [x] 2.3 `IncidentState.deployments`, carried like `flag_changes`
- [x] 2.4 Bind the collaborator in `assembling.py` over the read tier

## 3. The strategy chooses

- [x] 3.1 `MitigationStrategy.propose` and `propose_action` take
      `deployments: Sequence[ChangeEvent] = ()`; every existing strategy ignores
      it, and a test says so. `action_type` became `action_types`, a set, since
      the new strategy answers with either of two kinds
- [x] 3.2 The strategy for `SILENT_DATA_CORRUPTION`: flag revert where it answers,
      else the rollback where a deployment is recorded, else `None`
- [x] 3.3 Remap `SILENT_DATA_CORRUPTION` in `DEFAULT_STRATEGIES`
- [x] 3.4 Hand the deployments to `propose_action` in `proposing.py` and
      `candidates.py` - and to `what_each_would_do` from `investigating.py` and
      `choosing.py`, its two callers; `None` deployments answer as an empty
      history would for every mode but this one, and propose nothing for it

## 4. Proved for free, before anything is bought

- [x] 4.1 `lint`, `typecheck`, `guard_layering`, `test_all`
- [x] 4.2 A component test: the whole walk in-process with the agents doubled,
      a corruption candidate and a recorded deployment, reaching `RECOMMENDED`
      with the rollback as the recommendation
- [x] 4.3 The e2e case for the new scenario, proposed in chat
- [x] 4.4 `e2e_replay(mode='both')` over every existing scenario, via
      `/replay-run`, the new case deselected for want of a recording: 39 of 39
      in 29m16s
- [x] 4.5 The new case driven under the double on the flag walk's recorded
      answers (`silent-data-corruption`), so the paid run buys only the model's
      reading: passed in 24s - deploy history read, rollback of `io-shop`
      recommended, sync untouched

## 5. Bought

- [x] 5.1 `nox -s record` for the new scenario's `both-` corpus only, after
      `preflight-before-paid-runs`. Replay it and read what the model named:
      10 answers in 6 minutes, first walk; silent corruption blamed on deploy
      `26f1d7e`, rollback recommended, fix proposed. Both corruption cases
      replay green in 65s
- [x] 5.2 Report the record run's token spend: 23,002 output, 85,066 cache
      write, 96,165 cache read, 20 input
- [x] 5.3 An Investigator eval case: corruption named from a deployment, with
      `bad-deployment` as the near-miss. Written and collecting, not run

## 6. Written down

- [x] 6.1 `docs/spec-and-architecture.md`: §7.3's mapping says corruption's action
      follows the recorded change; §15.3 gains the scenario
- [x] 6.2 `docs/failure-modes-backlog.md`: FM-26 gains its second member; the
      "next" list moves up

## 7. Review before commit

- [x] 7.1 Docstrings made true: strategy-count comment, the flag revert's "only
      flag that moved" rule, `FetchDeployments`'s binding, `what_each_would_do`'s
      two unanswerable inputs, the second deploy-history read
- [x] 7.2 `DeploysBetween` -> `DeploymentsBetween`
- [x] 7.3 `flag_change_lookback_minutes` -> `mitigation_change_lookback_minutes`
      (config, tools, `.env.example`, three test lines); it sizes both histories
- [x] 7.4 Test cleanups, proposed in chat: the unreadable-deploy-history test
      asserts with the flag provider's helper and never checks which retrieval
      went unanswered; `_a_deployment` is duplicated across test_strategies and
      test_tools (lift to `agent_mitigation_test/framework/builders.py`);
      `WHAT_THE_PLATFORM_RECORDED` in test_investigating repeats `a_deployment()`;
      `_it_asked_for_the_window(_deployments)` -> `dont_care_deployments`
- [x] 7.5 Argus's own rollbacks dropped from the deploy history, test first. A
      new setting names the Argo CD account Argus acts as (counterpart of
      `unleash_actor`; Argo records it as `initiatedBy.username`, the read tier
      maps it to `ChangeEvent.actor`); `attribution.changes_not_made_by` made
      generic over anything with an `actor`; `fetch_recent_deployments` filters
      with it. Then correct its docstring, which claims the reader's action "is
      never taken" - false where no onset was stated
