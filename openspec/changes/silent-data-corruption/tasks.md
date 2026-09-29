## 1. The shop drifts

- [x] 1.1 Add the write path that records a purchase without adding it to the
      stored monthly total, behind the feature flag, in `Argus-Demo-Target-App`
- [x] 1.2 Leave `tests/io_shop` GREEN at head, with no test over the planted
      fault - the grader runs that suite before it writes any patch in and reads
      a red one as the service being unsound, which would fail every fix in the
      corpus rather than this one. Assert the fault is present in the harness
      suite beside it instead, which the grader never runs
- [x] 1.3 Commit and **push** both revisions, and put their hashes in the
      scenario definition with a comment saying no channel serves them: this
      scenario stages no deployment, the revision history is empty for a
      generated flag scenario, and Code-Fix works from main by code search as it
      does for a flag toggle. They are there for a person and for `grade_fixes`
- [x] 1.4 Stage the `silent-data-corruption` scenario: the flag, the accounts
      that drift, and a window in which every judged series sits at its baseline
- [x] 1.5 Assert the flatness directly - error rate, all three quantiles and
      memory at baseline in every minute, and no onset measurable from the window
- [x] 1.6 Add the console entry, under a foundational-integrity family the rail
      does not have yet, keyed to the published taxonomy's share

## 2. The check and its alert

- [x] 2.1 Write the integrity check: re-derive each shopper's monthly total from
      their purchases, count the accounts that disagree, find the largest gap and
      the oldest affected purchase
- [x] 2.2 Keep the check unreachable from outside the process, and let the stated
      interval be a constant the alert's prose quotes rather than a scheduler.
      Nothing in this service runs between requests by design, and a background
      job firing alerts on its own would race the e2e suite that stages the
      scenario. What autonomy rests on is that Argus cannot trigger it, which
      holds either way
- [x] 2.3 Fire an alert from it in the existing Grafana shape, under its own rule
      name, with the count, the largest gap and the oldest affected purchase in
      the summary
- [x] 2.4 Check that a quiet shop finds nothing and fires nothing

## 3. The kernel's new words

- [x] 3.1 `FailureMode.SILENT_DATA_CORRUPTION`, with the comment saying what
      separates it from the modes it shares a cause with - the damage outliving
      the change
- [x] 3.2 `IncidentStatus.RECOMMENDED`, terminal, with the comment saying what
      separates it from `ESCALATED`
- [x] 3.3 A sixth `Refusal` for an action nothing can confirm, and its row
      sentence in the gate's table - and in the narration's twin of that table,
      which has a totality test of its own

## 4. An onset the alert states

- [x] 4.1 Carry the stated onset from the alert payload through intake, without
      disturbing an alert that states none
- [x] 4.2 Use it when `find_onset` measures nothing, and leave the
      measured-onset and nothing-at-all branches byte-identical
- [x] 4.3 Say in the opening message that the onset came from the alert and that
      no series departs across it
- [x] 4.4 Anchor the change channels on the stated onset rather than on the
      alert, and check it holds for an onset older than the metrics source keeps
      - already true once 4.2 landed, since the dispatcher is built with the
      resolved onset; the test is what says so and what would catch it moving
- [x] 4.5 Anchor Mitigation's search for the flag to revert on the stated onset
      too. It looks in `[now() - flag_change_lookback_minutes, now]` today,
      which is sixty minutes and deliberately short - so a flag moved a week ago
      is invisible, Mitigation proposes nothing, and the incident escalates with
      no action to recommend. Anchor it rather than widening it: the sixty
      minutes is short on purpose, and a wide window makes "two flags changed,
      so no action" the common case

## 5. The gate declines

- [x] 5.0 Map `SILENT_DATA_CORRUPTION` to the existing flag-revert strategy in
      `DEFAULT_STRATEGIES` - without it Mitigation answers `None`, the refusal
      is *nothing answers this mode*, and the incident escalates with no action
      to recommend
- [x] 5.1 Refuse an action whose confirmation cannot arrive inside the
      verification window, in `gating.py`, with no model call
- [x] 5.2 End the mitigation phase on that refusal rather than reaching for the
      next candidate
- [x] 5.3 Record the refused action as the incident's recommendation
- [x] 5.4 Derive `RECOMMENDED` from that state, in preference to what the rest of
      the walk would produce, and keep the derivation total
- [x] 5.5 Check that every other refusal still reaches for the next candidate and
      still ends at `ESCALATED`

## 6. What is still owed, said everywhere

- [x] 6.1 Narrate the refusal and the recommendation
- [x] 6.2 Render `RECOMMENDED` on the incident page and the live view, naming the
      action and why nobody took it
- [x] 6.3 Put the recommended action among what the postmortem lists as
      outstanding
- [x] 6.4 Say it in the Slack message too

## 7. The fix and the repair

- [x] 7.1 Let a proposed fix carry a second file that repairs what the fault
      already wrote, in one pull request
- [x] 7.2 Say in the pull request body that the repair has not been run and that
      a person must run it
- [x] 7.3 Check that nothing in Code-Fix's binding can execute it
- [x] 7.4 Check an ordinary fix still carries the change alone

## 8. Proved for free, before anything is bought

- [x] 8.1 `lint`, `typecheck`, `guard_layering`, `test_all`
- [ ] 8.2 `grade_fixes` against the new corpus entry once one exists
- [x] 8.3 A component test for the scenario, driving the whole walk in-process
      with the agents doubled, proving it reaches `RECOMMENDED` and that the
      gate's refusal is not the model's to make. Not the e2e under the double
      this originally asked for: that would replay hand-authored answers, so it
      proves the same conditional - *given an investigation of this shape, the
      walk ends here* - at the cost of a fixture to keep honest in a module
      Claude may not edit. It found the ending had never been walked: the gate
      set the recommendation, the status derived from it, and the node narrated
      nothing, so the walk stopped at `tier_gate` with a `ValueError`
- [x] 8.4 `e2e_replay(mode='both')` over every existing scenario, proving the
      onset change broke none of them. 37 of 38 passed in 48:21; the one failure
      is this change's own new case, which has no recording until 9.1 runs and
      so cannot pass under replay. Nothing else moved

## 9. Bought

- [ ] 9.1 `nox -s record` for `both-silent-data-corruption` only - one corpus,
      and check no existing corpus moved. **Stop after the first walk and read
      its investigation before recording the rest.** Nothing free proves a real
      model, handed a flat window and a week-old onset, names a cause the gate
      then refuses - 8.3 proves the walk given that investigation, not that the
      model produces it. If it named none, the walk never reaches the gate, and
      stopping first costs one walk instead of a set
- [ ] 9.2 A real-API `e2e` run of the new test, and report the token spend
- [ ] 9.3 Investigator eval cases: the new mode named, and an action recommended
      rather than taken where nothing can confirm it

## 10. Written down

- [ ] 10.1 `docs/spec-and-architecture.md`: the mode, the stated onset, and
      verification deciding autonomy
- [ ] 10.2 `docs/failure-modes-backlog.md`: foundational integrity gains its
      first built member, and the deploy-caused sibling is written down as what
      follows it
