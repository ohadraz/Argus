Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel, agents,
then the walk.

## 1. Kernel

- [x] 1.1 `argus_core.budget` gains `StillWanted` and `wanted_throughout`
      (test: the default answers yes)
- [x] 1.2 `agent_mitigation` re-exports the kernel's `StillWanted` instead of
      defining its own; its private default goes in favour of
      `wanted_throughout`

## 2. Mitigation

- [x] 2.1 `take_action` asks `still_wanted` before `_perform`: not wanted →
      nothing performed, `Verdict.WITHDRAWN`, no undo descriptor, not measured
- [x] 2.2 A refuted change is still put back when the incident is withdrawn
      during the undo - true by construction: `_undone` takes no `still_wanted`,
      and the only new question is asked before `_perform`. No test: one would
      pin how many times the question is asked, not the behaviour

## 3. Investigator

- [x] 3.1 `Findings.stopped` (default False); a stopped Findings still carries
      one undetermined candidate
- [x] 3.2 `investigate` takes `still_wanted` and asks before every turn: not
      wanted → model not asked again, `Findings(stopped=True)`

## 4. Code-Fix

- [x] 4.1 `FixStopped`; `propose_fix` takes `still_wanted` and asks before every
      turn: not wanted → model not asked again, `FixStopped` raised, no branch
- [x] 4.2 `propose_fix` asks once more before `write_branch`: not wanted → no
      branch, no pull request, `FixStopped`

## 5. The walk

- [x] 5.1 `Investigate`, `ProposeFix` and `Fixer` ports gain a defaulted
      `still_wanted` keyword; hand-written stand-ins follow (mypy)
- [x] 5.2 `investigator_node` passes the bound question and returns an empty
      delta for stopped findings (no hypotheses, no reads, no memory search)
- [x] 5.3 `codefix_node` passes the bound question and turns `FixStopped` into
      an empty delta with no `FixAttempted`
- [x] 5.4 `with_status` asks `still_wanted` after the node returns: not wanted →
      the node's updates with `status: withdrawn`, nothing written
- [x] 5.5 `graph.py` / `assembling.py` thread `still_wanted` to the investigator
      and codefix nodes

## 6. Logging

- [x] 6.0 Each stop logs one INFO line, tested: Mitigation before acting,
      Investigator and Code-Fix between turns and before the write, and the walk's
      check after a step; Code-Fix's step drops its own copy of the agent's line

## 7. Verification

- [x] 7.1 Module suites green: argus_core, agent_mitigation, agent_investigator,
      agent_codefix, orchestrator; typecheck, lint, guard_layering
- [x] 7.2 `e2e_replay(mode='both')` withdrawal cases green (background)
- [ ] 7.3 Spec `incident-withdrawal` synced on archive
