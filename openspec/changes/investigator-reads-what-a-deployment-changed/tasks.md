## 1. Withdraw the false discriminator

- [x] 1.1 Revert the three sentences added to `CONFIG_INDUCED_FAILURE`'s meaning in
      `modules/argus_core/src/argus_core/models/failure_mode.py` - the claim that
      which of the two landed is the path the deployment shipped from. It is false
      in the fixture, where both scenarios ship from `deploy`, and it was measured
      not to work before this change existed.
- [x] 1.2 Rewrite `_what_it_shipped`'s docstring in
      `modules/read_mcp_server/src/read_mcp_server/argocd.py`. The summary line
      stays - saying the path is true and harmless - but its stated reason ("what
      landed is the path, and this is the only place that knows it") is the claim
      being withdrawn.
- [x] 1.3 Confirm `read_mcp_server`'s own suite still passes with the docstring
      rewritten and the summary unchanged.

## 2. The comparison, in `repository_source`

- [x] 2.1 Propose the test for a comparison that carries each file's change, in
      `modules/repository_source/tests/repository_source_test/`, mirroring the
      source module it covers.
- [x] 2.2 Add the second comparison reader beside `paths_changed_between`:
      same credential, same `RepositoryUnreadable`, answering per-file path and
      patch rather than a flat path list.
- [x] 2.3 Do not narrow the comparison to `github_source_paths`. That scope is
      `src/io_shop,tests/io_shop`, and the configuration a deployment ships lives
      outside the source tree by definition - scoped, the cache scenario's whole
      diagnosis vanishes and the answer says the deployment changed nothing. The
      reader takes no scope at all; bounding belongs to the tier that renders the
      answer (3.3).
- [x] 2.4 Export it from `repository_source/__init__.py` (`__all__` only; the
      package's `__init__` stays an export list).
- [x] 2.5 Green on `test_module(module='repository_source')`, `lint`, `typecheck`.

## 3. The read-tier tool

- [x] 3.1 Propose the tests for the new `read_mcp_server` module: the base revision
      taken from the entry before the named one, a revision with no predecessor, a
      revision the history does not hold, and an unreachable repository raising
      rather than answering emptily.
- [x] 3.2 Add the module. It reads Argo's history for the base revision and
      `repository_source` for the difference, with both sources as injection seams
      the way `argocd.py` and `registry.py` have them.
- [x] 3.3 Bound the answer where it is rendered - how many files it describes and
      how much of each file's patch it carries - and say what was left out, the way
      `search_repository` says its own ceiling was reached.
- [x] 3.3a Answer a non-deployment reference with the reason and the channel that
      does report flag changes, rather than with an empty comparison.
- [x] 3.4 Register the tool in `server.py` as a one-line delegation, with the
      docstring the model reads - what the channel answers, when it is worth
      calling, and that a path is never labelled code or configuration.
- [x] 3.5 Add the typed function to `read_mcp_client`, exported from its
      `__init__.py`.
- [x] 3.6 Green on `test_module(module='read_mcp_server')`,
      `test_module(module='read_mcp_client')`, `guard_exports`, `guard_layering`.
      Note: `guard_exports` stays red until 4.2 - nothing imports the new client
      function until the Investigator's channel does, and the guard is right to
      say so.

## 4. The Investigator's fifth channel

- [x] 4.1 Propose the tests: the channel's own tool module, the `Dispatcher` branch,
      the offered tool set, and that no windowed reading is recorded for it.
- [x] 4.2 Add the `Protocol` for the channel to `agent_investigator/retrieval.py`
      and the function that binds it over a read-tier connection, beside
      `dependencies_over`.
- [x] 4.3 Add `agent_investigator/tools/deployments.py` - the tool definition the
      model reads, and the function that serves one call. No `Reading`, for the
      reason the register channel records none.
- [x] 4.4 Add the branch to `Dispatcher._serve` and the channel to the message
      naming the tools that exist, and thread the fetcher through `investigate`.
- [x] 4.5 Add it to `investigator_tools()`.
- [x] 4.6 Correct `BRIEF`: it says "three ways to read evidence" and there are
      five. Say what the new channel is for, and that it composes with the change
      channel.
- [x] 4.7 Point `CONFIG_INDUCED_FAILURE`'s meaning at the channel - what separates
      the pair is what the deployment changed, and there is a tool that answers it.
- [x] 4.8 Green on `test_module(module='agent_investigator')`, `lint`, `typecheck`,
      `guard_layering`, `guard_exports`.

## 5. Wiring and the walk

- [x] 5.1 Thread the new channel through the orchestrator's construction of the
      Investigator, wherever the other four are bound.
- [x] 5.2 Green on `test_module(module='orchestrator')` and `test_all`.
- [x] 5.3 Green on `integration`, which brings up its own postgres.

## 6. The evidence, paid for

- [x] 6.1 Run the preflight for a paid run - everything free must be green first,
      and the stack must come up with the fifth tool in the list.
- [x] 6.2 Add the Investigator eval case for the pair: two deployments from the
      same path, one changing configuration and one changing source, with the
      answer asserted rather than the reasoning. It is the case that would have
      caught this, and nothing in the eval currently distinguishes the two.
- [x] 6.2a Worked out which existing evals this changes. No case demands an answer
      its own evidence now forbids - the FM-23 failure mode does not recur. The
      digest does the separation on its own: all six pooled cases sit at
      `33a135e3fc06`, and both `BRIEF` and the tool list moved, so their recorded
      rates describe a configuration that no longer runs; the preamble now says
      that re-measure is owed. `unrelated-change-is-not-blamed` was given its
      deploy's diff - a log level in a values file, no source - so a model can
      decline to blame it from something it read rather than from knowing nothing
      about it. The forty calm minutes are still what makes it unrelated; the diff
      is a second, independent reason.
- [x] 6.3 Re-record `both` against the real API. The tool list changed, so every
      corpus in that mode is an answer to a question no longer asked.
- [x] 6.4 Run `e2e_replay(mode='both')` and confirm
      `test_a_misconfigured_cache_is_rolled_back` answers
      `config-induced-failure`, with all 26 green.
- [x] 6.5 Confirm no `both-cache-misconfigured*` recording from before this change
      survives in the tree. That corpus records the walk concluding
      `bad-deployment` from the evidence this change replaces, and it is the one
      the red case replays - so it is superseded rather than stale, and this change
      is not done while a single turn of it is still on disk. Check the count as
      well as the content: the re-record may produce fewer turns than the eleven
      now there, and a leftover high-numbered file replays into the middle of a
      new walk.
- [x] 6.6 Token spend reported: 217,320 in + 1,254,615 out, 592,236 cache writes
      and 217,320 cache reads over 104 turns - about $29.29 at Opus list rates.
      Summed from the recordings rather than the replay log, since the stack had
      torn itself down by the time the run reported.
- [ ] 6.7 Re-record `grep` and `meaning` only if their modes are needed again; note
      in the handover that they are stale evidence rather than broken.

## 7. Two defects the verification run exposed

The first `e2e_replay` after the re-record came back 25 of 26, failing on
`test_a_slow_rollout_is_reverted` - which then passed alone, and passed again in a
full rerun. Diagnosed rather than re-run: the mitigation was applied and undone
188 seconds later, so the verification window elapsed without recovery ever being
confirmed once.

- [x] 7.1 Find the cause. An error rate idling at half a percent has a departure
      bar of `0.005 + 3 * 0.01`, which in binary floating point is
      0.034999999999999996; a minute reporting seven failures in two hundred
      requests is 0.035. The series "departed" by 6.94e-18, escaped the exclusion
      written for signals with no incident in them, and was handed a recovery
      ceiling its own worst minute cleared by the same nothing. Reproduced through
      `has_recovered_since` directly: that minute refuses recovery, one step lower
      grants it.
- [x] 7.2 Fix it where the two answers disagree. `_subsided_threshold` compared
      `at_its_worst` to `departed` exactly, though both answer the same question -
      did this signal ever depart. The margin is now one step of what the calm
      minutes resolve, and no wider: anything wider would have the module's two
      answers disagree about a difference the series *can* express. A failing test
      came first.
- [x] 7.3 Raise the fixture's settling period from one minute to three, its own
      default. One settling minute freezes the window with exactly one minute
      after a revert, so the rule can only ask whether *every* minute is still at
      the incident's level and its own tolerance for a lone noisy minute is
      unreachable - and polling cannot change a frozen answer. Independent of 7.2,
      and it removes the class rather than the instance.
- [x] 7.4 Fix the fixture's flag timelines, which reconciled in one direction
      only: once closed, a flag switched back on never reopened them, so the shop
      reported the flag where it no longer was. Both the staged flag and the decoy
      now go through one reconciliation. `docs/spec-and-architecture.md` §15
      already required this - "a flag changed by anyone takes effect on the next
      request without this service being told" - so the fixture was the thing out
      of step, not the spec.
- [x] 7.5 Say the precision rule in the spec, beside the two paragraphs it sits
      between: whether a signal ever moved is decided to the precision the signal
      has.
- [x] 7.6 Re-run `test_all`, `integration` and `e2e_replay(mode='both')` against
      the kernel fix and the fixture changes. The earlier green runs were taken
      before them.

## 8. Close out

- [x] 8.0 Update `docs/failure-modes-backlog.md` as needed: the entry for the
      config-induced pair should say what now separates it from a bad deployment,
      and any note claiming the distinction is unreachable is no longer true.
- [x] 8.1 Fold the change into `docs/spec-and-architecture.md` as though the design
      had always had five channels.
- [ ] 8.2 Commit in subjects, one line each, approved before each commit.
- [ ] 8.3 Archive the change as its own separate commit.
