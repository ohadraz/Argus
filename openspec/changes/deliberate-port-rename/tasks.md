Every Argus-side item below is a TDD cycle: the test is proposed in chat, the
user pastes it, and the implementation follows it. `Argus-Demo-Target-App` is a
fixture and is covered after the fact, not before.

## 1. The fixture

- [x] 1.1 Add `deploy/scrape.yaml` to the demo app's `main` in its own commit,
      selecting the metrics port by `port: metrics`; leave `9f4ad14`, `e283ba3`
      and every `src/io_shop` file untouched
- [x] 1.2 Check `tests/io_shop` and `tests/target_app` stay green on `main`
- [x] 1.3 Stage the revision pair on unmerged branch
      `deploy/ports-named-for-protocol`: a parent naming two or more ports the
      old way, a tip renaming all of them to `<protocol>[-<purpose>]` with a
      comment stating the convention
- [x] 1.4 Add scenario id `monitoring-configuration-drift`: the blind spot's
      outage, alert and onset, deployed from that pair; reset restores collecting
- [x] 1.5 Cover it in the demo app's suite: the diff renames more than one port to
      one rule (checked by hand on `53f02e9`; the suite reads no git); rows stop at
      the onset; a restart changes nothing; reset restores
- [x] 1.6 Add the console entry beside `monitoring-blind-spot`
- [x] 1.7 Push the demo app - Code-Fix reads GitHub, not disk

## 2. The mode

- [x] 2.1 `FailureMode.MONITORING_CONFIGURATION_DRIFT` and its `meaning()`,
      separated from `monitoring-blind-spot` and `config-induced-failure`
- [x] 2.2 No entry in `DEFAULT_STRATEGIES`; `a_mitigation_answers` is false for it
- [x] 2.3 Check the Investigator's offered mode list picks it up with no further
      change

## 3. The walk

- [x] 3.1 `NOTHING_ANSWERS_THIS_MODE` routes to Code-Fix and records the fact on
      the state
- [x] 3.2 `status_after` derives `fixing` from that fact until Code-Fix answers, and
      `escalated` after it, with and without a fix
- [x] 3.3 Walk test: leading candidate unanswerable, second answerable by a
      rollback - no action proposed, Investigator not asked again, Code-Fix runs
- [x] 3.4 Run `e2e_replay` for the upstream case in both modes, free, and record
      whether its recordings still replay - both and grep pass, 1 of 1 each

## 4. Code-Fix scope

- [x] 4.1 `GITHUB_SOURCE_PATHS` gains `deploy` in `noxfile.py`, `.env.example`
      and the local `.env`
- [x] 4.2 Propose the `github_double` change in chat: `main` carries `deploy/` -
      not needed: a paid run reads the real repository, and a replay replays
      Code-Fix's answers, so the double's copy of `deploy/` decides nothing
- [x] 4.3 Check the code index embeds the `deploy/` files and both channels answer
      the same scope - by construction: `chunks_of` windows any non-Python file,
      and both channels filter through `belongs_to_the_service`

## 5. The postmortem

- [x] 5.1 Compute whether the sight was restored from the metrics at write time
- [x] 5.2 State it in the document when it was not, naming the onset minute
- [x] 5.3 Check a restored blind spot's postmortem carries no such statement -
      `test_an_incident_whose_metrics_went_on_was_observed_throughout`

## 6. End to end

- [x] 6.1 Propose the e2e case in chat: the mode named, no rollback taken, a fix
      proposed touching `deploy/scrape.yaml` with its test, the sight still lost,
      `escalated`
- [x] 6.2 Prove the walk under the double with hand-authored answers - the case
      passes, and `grade_fixes` grades the fabricated fix green
- [x] 6.3 Full `e2e_replay` in `both` mode, green, before any recording - 41 of 41,
      30 minutes, against the fabricated drift set
- [x] 6.4 Preflight, then record `both-monitoring-configuration-drift` (paid) - drift
      0.88 over blind spot 0.3, refused, PR #95, escalated; replays green
- [x] 6.5 Re-record the upstream corpora if 3.4 found them stale (paid) - not needed
- [x] 6.6 Add the scenario to `THE_RECORDINGS_THAT_MUST_CARRY_A_FIX`; `grade_fixes`
      green - 19 of 19, after the grader learned to read the last submission
- [x] 6.7 The new e2e case asserts its cause with `cause_identified_as`, a framework
      assertion that checks the mode and the confidence together - no
      `about_the_hypothesis` wrapper at the call site

## 7. Docs

- [x] 7.1 `docs/spec-and-architecture.md`: the mode, and a mode nothing answers
      going straight to Code-Fix
- [x] 7.2 `docs/failure-modes-backlog.md`: FM-27's deliberate variant built
