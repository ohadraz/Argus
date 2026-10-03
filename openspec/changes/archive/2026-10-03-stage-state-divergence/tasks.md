Every task that adds behaviour is preceded by its failing test. Tests under
`tests/`, `modules/*/tests/`, `argus_testkit` and either double are proposed in chat
for the user to paste - whole file, never a fragment. `Argus-Demo-Target-App` is
outside that rule and its tests are written directly, after the code.

**No test in the Argus repo asserts a figure the fixture chose.** Where a count
matters it is asserted as a relation between two things Argus holds, plus a claim
that Argus acted at all - a bare relation is satisfied by zero equals zero.

## 1. A real cache in the Target Environment

- [x] 1.1 Add `redis:7-alpine` to **`Argus-Demo-Target-App/docker-compose.yml`**,
      with a network alias for `cache.io-shop.svc.cluster.local` so the address in
      `deploy/values-production.yaml` resolves for the first time without that
      frozen file changing, and a `depends_on` from `target-service`. Not the root
      compose file, which `include`s the demo app's and refuses a re-declared
      service name
- [x] 1.2a Add `cache_url` to `argus_core.config.Settings` and `CACHE_URL` to
      `.env.example`, defaulting to `redis://localhost:6379` - Argus is a host
      process and can resolve neither the cluster DNS name nor the container alias,
      so the shop and Argus hold different addresses for one cache, which is the
      asymmetry `host.docker.internal` already lives with
- [x] 1.2b Add the settings slice that carries it, in the file the Redis seam lands
      in - a `SettingsSlice` lives with its consumer, as `RestartSettings` lives in
      `restarting.py`, so there is nowhere to put it until 8.2 exists. Its failing
      test is the slice narrowing from `Settings` and carrying the endpoint, which
      has precedent; a field's plain default is not tested anywhere here and should
      not start being, for the reason a fixture figure is not asserted

Nothing is owed to the pre-run port check or teardown: that check guards Argus's
leaked **host processes**, and a compose container's lifetime is `compose down`'s. A
host already holding 6379 fails the bind loudly, which is the failure the check
exists to prevent and cannot happen here. The demo app's cache endpoint already
exists (`the_deployed_cache_endpoint`, `the_working_cache_endpoint`) and comes from
the values file rather than the environment, deliberately.

## 2. The shop keeps real entries for this scenario only

- [x] 2.1 Hand this scenario a `LookUpSummary` backed by a real Redis client,
      through `_the_cache_answering`'s existing shape - it already returns `None`
      where a scenario has no cache, so a different implementation per scenario is
      the shape that is there rather than a new branch. `summary_cache.py` is not
      touched
- [x] 2.2 Hold the invariant that guarantees no other scenario moves: both of
      `_the_cache_answering`'s entropy draws stay unconditional and in order, so a
      request that skips the cache cannot shift the sequence after it. Verify
      before writing the seam, not after
- [x] 2.3 Keep the real client wired to this scenario alone, and write down why:
      with Redis listening on 6379, a shop dialling the deployed 6380 would be
      *genuinely* refused, which turns `cache-misconfigured` from arithmetic into a
      real outage and breaks its recordings. Nothing may "upgrade" that scenario to
      the real cache without re-recording it

## 3. The promoted stale replica

- [x] 3.1 Add the scenario: `STATE_DIVERGENCE = "cache-failed-over"`, its title,
      description and family, with the `Scenario` flag that stages it
- [x] 3.2 Seed, for each active account, the figure its entry held at the minute
      replication broke - three hours before the promotion. Nothing rewrites an
      entry afterwards; the fixture has no cache write path and is not given one
- [x] 3.3 Derive the stale share from `SOMEBODY_BUYS_EVERY` rather than hardcoding
      it, so both integrity scenarios stay tied to one grid: the lag in minutes over
      two, capped at the accounts the check examines
- [x] 3.4 Accept that the set grows - an account diverges as soon as it buys after
      the lag began - and say so wherever the scenario is described
- [x] 3.5 Leave every judged series flat across the window: error rate, p50, p95,
      p99, heap, CPU, replicas
- [x] 3.6 Log the reconnection to a new primary at the promotion minute, so the
      onset has corroboration in a channel Argus already reads
- [x] 3.7 Make a discarded entry render correctly from the ledger, and leave the
      promoted standby serving on the endpoint the deployment configured

## 4. The shop's own check finds it

- [x] 4.1 Add the comparison to `io_shop`: what the cache holds against the
      purchases behind it, returning a value as `reconcile_monthly_totals` does, and
      carrying each stale entry's key, its gap in cents and its item-count
      discrepancy - `SummaryEntry` holds `items_counted` as well as `amount_cents`,
      so an entry diverges in two fields
- [x] 4.2 Fire the alert: how many disagree, out of how many checked, the widest
      gap, the item discrepancy, the keys, and the onset - which is the **promotion**
      minute, not the oldest missing purchase. The oldest missing purchase dates the
      replication break and is carried as that, three hours earlier
- [x] 4.3 Make the key list's length equal the disagreeing count, and assert it on
      this side too - two fields that check each other, so a truncated list fails
      loudly instead of reading as a smaller incident
- [x] 4.4 Say in the payload that the key list is a snapshot at check time
- [x] 4.5 Cover the comparison and the share-against-the-grid in the demo app's own
      suite, after the code - its own safety net against a regenerated grid, with
      nothing in Argus depending on it

## 5. The mode

- [x] 5.1 Propose the test for `FailureMode.STATE_DIVERGENCE` and its meaning text,
      including the pair tests against `SILENT_DATA_CORRUPTION` and
      `IN_FLIGHT_COMPATIBILITY_BREAK`
- [x] 5.2 Add the value, the maintainer's comment and the model-facing meaning -
      which must separate the two dates, since a reader who takes the older one
      dates the incident from before anybody could have seen it

## 6. The alert carries addresses, and the model never sees them

- [x] 6.1 Propose the test for the alert model carrying the keys and the count that
      cross-checks them. Only those two are typed: the counts, the gap, the item
      discrepancy and the snapshot framing travel in `summary` as prose, as the
      reconciliation's figures already do, because the model reads those and only
      the action consumes the keys
- [x] 6.2 Add the fields, and parse them where the alert is read - one
      comma-separated annotation, where a key holding a comma splits into two
      plausible addresses and the count cross-check is what catches it, as it
      catches a truncated list
- [x] 6.3 ~~the keys reaching the findings~~ - they do not. All three
      `propose_action` call sites already hold `state.alert`, so the keys ride the
      alert they arrived on and `Findings` is unchanged. The cross-check is the
      alert's own, done in 6.1
- [x] 6.4 Widen the strategy protocol so a proposal can be handed the keys, and
      pass `state.alert.stale_entry_keys` at all three call sites. Every strategy
      declares the parameter and five of them ignore it, as five already ignore
      `flag_changes` - a protocol that fixed a parameter for one implementation
      would be a protocol nobody else could be called by. The widening landed with 9.2; **passing the keys at
      the three call sites is still owed** and needs the orchestrator's own test. One test
      double implements the protocol (`_StandInStrategy`) and needs the parameter
- [x] 6.5 Propose the test that **no key is rendered into any prompt** - the model
      reads the counts, the gap and the dates and nothing else. Two guards, one per
      place an `Alert` becomes model-bound text: the Investigator's conversation
      (`test_investigation.py`, asserted over every turn rather than the opening
      message, since a tool result carrying a key is the same leak) and the text an
      incident is found by (`test_describing.py`, which the embedder reads). Both
      passed on arrival, so both were shown to be sensitive rather than vacuous -
      a key added to each render, the guard watched to go red, the render put back
- [x] 6.6 ~~Make that true wherever an alert or a finding is rendered~~ - it already
      was. No site renders a whole `Alert`; every prompt builder picks fields by
      name and no builder picks these two. Inventing a filter to make a passing
      test pass would be a mechanism with nothing to stop. What this left is the
      near-miss: `_what_was_alerted` in `gathering.py` reads two fields out of a
      whole serialised alert that holds the keys, so the keys are already in that
      dict and a line rendering more of it would reach the postmortem's prompt
      unremarked. Said there, where the next person to widen it will be standing

## 7. The action

- [x] 7.1 Propose the test for `DiscardCacheEntries` - the keys it carries, and that
      it declares no undo is owed rather than none was found
- [x] 7.2 Add the action and its action type, a third `Platform` for the store it
      reaches, and the discard's branch in every exhaustive match in the kernel
- [x] 7.3 Propose the test for an action kind declaring whether it reports what it
      changed
- [x] 7.4 Add that declaration beside the kind, and the count the action reports

## 8. The write tier reaches the cache

- [x] 8.1 Propose the test for the Redis seam: one call carrying every key, the
      count returned, keys already gone counted as not removed, and an unreachable
      cache raising with the endpoint it dialled named
- [x] 8.2 Add the seam to `write_mcp_server`, in the shape `restarting.py` has - an
      endpoint from settings, a call, a failure that names what it dialled
- [x] 8.3 Propose the test for the tool rejecting a call that names no keys. The
      schema has no pattern to reject - it takes a list of keys and nothing that
      could match one it was not given - but an empty list is a call the schema
      permits and the store refuses, which would be reported as an unreachable
      cache and narrow the walk away from a store that is well
- [x] 8.4 Add the tool, its schema and its description saying the write reaches the
      cache itself rather than a control plane
- [x] 8.5 Add the typed function to `write_mcp_client`, untested in that module's
      own suite as `scale_out` and `pin_autoscaler` are - a typed wrapper's claim is
      only true against a real server, which is the stack's to prove
- [x] 8.6 ~~contract test for the tool's schema~~ - there is no such suite.
      `tests/contract/` holds the Anthropic and Slack doubles, which stand in for
      genuinely external parties; Argus's own write tier is not external to its own
      agents, however many module boundaries sit between them

## 9. Proposing it, and being allowed to

- [x] 9.1 Propose the test for the strategy: the keys from the evidence exactly and
      entirely, `None` where none were named, and no key ever composed
- [x] 9.2 Add the strategy, taking the keys as a parameter beside `flag_changes`
- [x] 9.3 Propose the test for `DEFAULT_STRATEGIES` answering `STATE_DIVERGENCE` and
      for `GENERIC_MITIGATIONS` admitting the discard
- [x] 9.4 Register both, with the comment saying why membership is still the whole
      criterion for an action that removes rather than restores

## 10. Judging the attempt

- [x] 10.1 Propose the test for a third sibling predicate over the window: whether
      it holds a departure to have recovered *from*, sharing
      `_first_index_at_or_after` with the two that are there
- [x] 10.2 Add it beside `has_a_reading_since`, leaving `has_recovered_since`'s
      signature and docstring alone - the defect is that its precondition is
      documented, unenforced and unaskable, not that it lies
- [x] 10.3 Propose the test for the caller asking the sibling first, and confirming
      from the receipt where the action's kind reports one
- [x] 10.4 Propose the test for an action with no receipt left unconfirmed in a flat
      window - the restart case - and for a measured onset judged on levels exactly
      as before
- [x] 10.5 Change the caller. The window is asked for a departure once, and the two
      arms read that one answer differently: a kind that reports what it changed is
      settled by its receipt wherever no departure is there to judge it - whether the
      series were flat or nobody published them - while a kind with no receipt is
      refuted only where the minutes *were* published and never moved. Keeping the
      receipt behind the coverage measurement as well withheld it from every incident
      of this mode: an incident that moves no series publishes no minutes between its
      onset and the action, so the sight read as absent for a fully observed service
      and the one confirmation a discard can ever get was never reached. Landed
      before the two tests that hold it (`test_trying.py:2400` and `:2446`), which is
      TDD debt and recorded as that; the first was verified red against the previous
      condition before it was accepted
- [x] 10.6 Propose the test for the gate: a flat-window incident whose action
      reports its effect is taken rather than recommended
- [x] 10.7 Change the unconfirmability judgement to read the action's kind
- [x] 10.8 The attempt records which rule settled it, and the record is the
      `because` sentence: the call site stopped hardcoding "the service returned to
      baseline" and now carries the reason the watching gave, which is where every
      reader of the incident meets it

## 11. Unwinding, and withdrawal

- [x] 11.1 Propose the test for a refuted discard writing nothing back and saying
      the action needed no undo
- [x] 11.2 Propose the test for a withdrawal of a discard-mitigated incident doing
      the same, and not reading as an undo that failed
- [x] 11.3 Implement both paths. Landed in four steps, deliberately separated: the
      fallthrough in `_undone` became an exhaustive match *before* the member it
      would have mis-narrated existed, since "anything else" there meant the
      restore's own sentence; then `Undone.NO_UNDO_WAS_OWED` and
      `_what_became_of_it`, which stopped being a dict because a lookup answers an
      unhandled member with a `KeyError` while a page is being rendered; then the
      two paths, on `changes_something_persistent` rather than on the kind compared
      in two modules; then the unwind's docstring, which named two silences and
      had three. `_undone` takes the kind as a parameter, because `Performed` says
      deliberately that the kind lives on the row

## 12. Saying it

- [x] 12.1 Propose the test for the narration of the discard: said as stale cached
      *figures* thrown away rather than as data deleted, in both the past tense a
      line about what was done uses and the gerund the demotion line uses
- [x] 12.2 Propose the test for the narration of its withdrawal
- [x] 12.3 ~~Add both lines~~ - both are in, and neither was added here. The
      discard's two spellings landed with 12.1, and the withdrawal's arrived as a
      branch of `_what_became_of_it` under 11.3, because making that lookup
      exhaustive is what forced a phrase for the new member rather than a
      `KeyError`. Written when neither line existed; nothing is owed, and both are
      covered - the discard's by 12.1's pair, the withdrawal's by 12.2

## 13. End to end

- [x] 13.1 Propose the e2e case, asserting Argus and never the fixture: the mode is
      determined as state divergence, the onset Argus holds is the one the alert
      stated, the count discarded equals the count the evidence named **and is not
      zero**, and the incident ends `MITIGATED`
- [x] 13.2 Propose the eval case separating this mode from `silent-data-corruption`,
      since a reader who confuses them reaches an action that repairs nothing
- [x] 13.3 Add the case to the noxfile's mode selection, uncollected where its
      recording does not exist rather than skipped. The `meaning` mode earned a
      name of its own, since something now compares against it. One thing beyond
      the task: `scripts/record_incident.py` had no entry for this scenario, so
      13.4 had nothing to drive - the mapping is what says which scenario a name
      stages and what the walk must publish, and it is free to add
- [x] 13.4 Record it under `both`, after everything else is green against the
      double. A recording *contains* fixture figures as evidence of a real walk and
      is not a test asserting them - nothing to scrub. **`grep` is not recorded, and
      that is an accepted gap rather than an oversight**: a capture is a real
      investigation against the real API, and this project does not have the money
      for a second one. The intent is unchanged - every case is meant to pass in
      every mode, and the recording is wanted the day it can be afforded - so the
      case stays collected under `grep` and that run stays red on a missing
      recording. Widening the noxfile's ignore to cover `grep` was refused and stays
      refused: a mode that passes because the case was left out of it is worse than
      one that fails because a recording is missing. The gap is accepted in this
      record, not hidden in the tooling, and nobody needs to be asked about it again

## 14. Documentation

- [x] 14.1 `docs/failure-modes-backlog.md`: FM-31 built, foundational integrity
      covered entire, what the mode added beyond the scenario, and the table row
- [x] 14.2 `docs/spec-and-architecture.md`: the sixth generic mitigation, the third
      confirmation rule, and the write tier reaching a datastore - as specification,
      not changelog
- [x] 14.3 ~~`CLAUDE.md`: Redis in the stack, if the run instructions change~~ - they
      do not. No new command, no new flag, no step before any session: the demo
      app's own compose brings the cache up with the rest of the stack, and every
      session that needed the stack already brought it up. The file names no host
      port for postgres or Qdrant either, so naming one for the cache would be the
      only entry of its kind. The one thing that changed is a loud failure - a host
      already holding 6379 fails the bind, which is the failure a port check exists
      to produce and needs no instruction to interpret

## 15. Verification

Every figure here is measured, and each item is ticked against the tree it was
measured on rather than inherited from an earlier one - an earlier green describes
an earlier tree. The four free items below were measured in one pass over one
tree, after the last defect landed. The fifth is ticked at the scope its owner
set: the `grep` recording is not bought, so it is not run, and 13.4 carries the
reason.

- [x] 15.1 `lint`, `guard_layering`, `guard_e2e_boundary`, `typecheck` - all four
      green in one pass
- [x] 15.2 `test_all` - **21 suites, 1,787 passed, 2 minutes**, the three new
      confirmation cases among `agent_mitigation`'s 180
- [x] 15.3 `integration` - **8 passed, 42 seconds**
- [x] 15.4 `e2e_replay(mode='both')`, green, counts reported - **38 passed, 0
      failed, 29m23s**, with the blind spot and the stale cache green in one run,
      on a machine with nothing else on it. The baseline is 29m19s, and the four
      seconds between them are what closed a day's argument about contention: two
      orphaned `pytest tests/e2e` suites, invisible to a port check, had been
      truncating each other's database and draining the double's one queue.
      `grep` is not recorded and is not run: see 13.4, where the gap is stated and
      accepted. Ticked because every verification this change can afford has been
      performed and has passed, which is what finished means at the scope its owner
      set - not because `grep` was made to look green
- [x] 15.5 Demo app's own suite green, `grade_fixes` unaffected - **587 passed** at
      `e9ba79c`, tree clean before and after, and `grade_fixes` **15 passed in 24
      seconds**. One more than the corpus held: this scenario's own fix is graded
      beside the rest, which is what "unaffected" has to mean once a change adds a
      gradeable case
