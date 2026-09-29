## 1. The two revisions in the Target Service

- [x] 1.1 Change the shape of what `io_shop/summary_cache.py` stores, as one
      commit on `Argus-Demo-Target-App`'s main branch: the writer puts the new
      shape in and the reader reads only the new shape. **No read path for the old
      one** - that omission is the defect, and it is the expand step of an
      expand-contract migration stated in code. Comment it the way the shop's
      other modules are commented: what the entry now holds, not that anything is
      wrong.
- [x] 1.2 Run `tests/io_shop` at that commit and at its parent, and confirm both
      are green. This is the claim the whole mode rests on - neither revision is
      at fault - and it is a fact about the fixture rather than a sentence in a
      description. If a test goes red at either end, the commit is the wrong
      commit.
- [x] 1.3 Record the two hashes as constants in `scenarios.py`, beside
      `THE_COMMIT_THAT_MOVED_THE_CACHE_PORT` and its parent, and for the reason
      those are constants: the commit cannot name itself.
- [x] 1.4 Cover the new entry shape in the demo app's own tests, after the code -
      a regression net, not a specification.

## 2. The rollout as live state in the fixture

- [x] 2.1 Add the paused rollout to `ScenarioState` in
      `Argus-Demo-Target-App/src/target_app/state.py`: a `PausedRollout` stretch
      beside `CacheOutage` and `SlowDeployment`, carrying when it began and when
      it ended. The same `None`-everywhere-else treatment, which is what keeps
      every other scenario's fleet on one revision.
- [x] 2.2 Report the split on the Deployment manifest that
      `GET /argocd/{application}/resource` already serves: `status.replicas`,
      `status.updatedReplicas` and `spec.paused` beside the `spec.replicas` it
      carries today. Real fields on the real resource - nothing invented, and no
      new route.
- [x] 2.3 End the stretch in `roll_the_deployment_back`, as the third branch
      beside the cache outage and the slow deployment. Ended rather than cleared,
      for the reason those are ended: the minutes the shop spent failing are what
      happened.
- [x] 2.4 Answer for it in `phase()` and `generated_window()`, settled the same
      way a rollback's other two are - the point of watching past a rollback is to
      see the error rate come down and stay down.
- [x] 2.5 Cover 2.1-2.4 in `tests/target_app/`, written after the code.

## 3. The mixture in the generator

- [x] 3.1 Give each served page a side of the fleet, drawn at the split the
      scenario stages, and fail it when a page served by the older side reads a
      summary-cache entry the newer side wrote. One direction only - the older
      side cannot read a shape that did not exist, and the newer side reading the
      old one is the read path the migration never wrote.
- [x] 3.2 Let the failing share fall out of the arithmetic rather than be a
      constant: the share written by the newer side, times the share read by the
      older one, times how much of the traffic the cache answers at all. It is
      then zero at both ends of a rollout and largest in the middle by
      construction, which is the property the scenario is for and not a figure
      somebody chose.
- [x] 3.3 Leave every quantile, the heap and the CPU pair where they are. Pages
      fail fast on an entry they cannot read, so nothing waits - and a fixture
      that moved latency too would blur the collision with the flag scenario that
      makes this incident hard.
- [x] 3.4 Keep `cache_hit_ratio` at a working cache's ratio. The cache is up and
      answering; what is wrong is what two versions of the shop put in it, and a
      hit ratio that dipped would point at the neighbour scenario's fault.
- [x] 3.5 Write the failures into the log lines: an entry that could not be read,
      naming neither a flag nor a release. The logs say what the service said, and
      what it said is that it could not parse something it found.
- [x] 3.6 Cover in `tests/target_app/`: the same window read twice is identical;
      the error rate is elevated and the quantiles are not; the hit ratio is
      unchanged; a rollback takes the error rate back to baseline; a restart
      changes nothing but the start time.

## 4. The shape the detector needs

- [x] 4.1 Assert against the real detector, free, before anything is built on it:
      an onset is dated inside the incident, and a stretch after a rollback
      confirms recovery while a stretch after a restart does not. A steady
      elevated rate has none of the flapping scenario's subtlety, but the check is
      the same check and costs nothing.
- [x] 4.2 Propose the test for 4.1 - it is `tests/`, so it comes over as a whole
      file the human pastes.

## 5. The scenario

- [x] 5.1 Add `half-finished-rollout` to `SCENARIOS` in `scenarios.py`: a
      `rollout_is_paused` flag on `Scenario`, the title, the `ScenarioDeploy`
      naming the two commits from 1.3, and a description saying that a revision
      went out, that the rolling update was paused half-way, that both revisions
      are correct, and that what fails is the requests that cross between them.
- [x] 5.2 Add `rollout_is_paused` to `stages_a_flag`'s exclusions, so nothing
      offers a flag as the thing that breaks it.
- [x] 5.3 Give it a console family of its own. The taxonomy family is tail/outlier
      at 3%, which `THE_TAIL`'s blurb cannot stretch to - that group is about an
      incident living in the 99th percentile, and this one lives in the error
      rate. Name it for the rollout, quote the same 3%, and say in its blurb what
      the family has in common: a fault that exists only for part of the traffic,
      for reasons arithmetic rather than accidental.
- [x] 5.4 Give it the error-rate alert rule in `monitoring.py` that the flag
      scenarios have. The error rate is the only judged series this incident
      moves, and without a rule nothing pages and no walk starts.
- [x] 5.5 Offer it in the console. The split fleet on the page is the story, so
      unlike `monthly-statement-panel` it is not hidden.
- [x] 5.6 Confirm by hand: seed it, watch the error rate step with the quantiles
      flat; restart and watch nothing change; roll the deployment back and watch
      the rate come down; withdraw it and watch the rate return.

## 6. The mode

- [x] 6.1 Add `IN_FLIGHT_COMPATIBILITY_BREAK` to `FailureMode`, with the
      maintainer's comment saying why it is not one mode with a bad deployment:
      there the revision carried the fault, here neither revision did and what is
      wrong is that both are serving. Say that it is the one mode in the set with
      no culprit commit, because that is what a maintainer reading the list needs
      to know before adding the next one.
- [x] 6.2 Write its `meaning()` for the model reading evidence. It has a
      neighbour on each side and must point at both: the metrics are a flag
      toggle's, so read the flag history; the change channel is a bad
      deployment's, so read whether the rollout converged before blaming the
      revision.
- [x] 6.3 Widen `BAD_DEPLOYMENT`'s own meaning to point back, as the leak's points
      at saturation. A pair is only told apart if both halves say what the other
      one is.

## 7. The sixth retrieval channel

- [x] 7.1 Add `rollouts.py` to `read_mcp_server` beside `deployments.py`: read the
      live Deployment through the platform's managed-resource endpoint and report
      the revision being converged on, how many replicas have reached it, how many
      have not, whether the rolling update is paused, and when that state began.
- [x] 7.2 Report state and draw no conclusion, as `deployments.py` says what
      changed and leaves the reading. A rollout part way through is the ordinary
      condition of every deployment for a minute or two, and a channel that called
      one a fault would be deciding, on a timing it cannot know, something that
      belongs to whoever weighs causes.
- [x] 7.3 Answer plainly for an application that converged. A channel that said
      nothing about a finished deployment is one a reader consults only when they
      already suspect the answer - and in twelve of the thirteen scenarios the
      right answer is "it finished", which is evidence too.
- [x] 7.4 Fail as the change channels fail where the platform cannot be reached.
      An unreachable platform must never answer that the deployment converged.
- [x] 7.5 Give the read tier its own settings slice for that route, and check
      `.env.example`. Nothing new is needed in either: `argocd_resource_path`
      is already a field on `Settings` and already in `.env.example`, because the
      write tier reads the same endpoint for the count a scale-out replaces. What
      the read tier needs is its own *slice* over it - `RolloutReadSettings`
      beside `ArgocdSettings` - which is the tier split rather than a second
      value.
- [x] 7.6 Register the tool on the server and add the typed function to
      `read_mcp_client`, as `what_a_deployment_changed`'s pair are.

## 8. Diagnosing it

- [x] 8.1 Register `IN_FLIGHT_COMPATIBILITY_BREAK` against the existing
      `RollbackDeploymentStrategy` in `DEFAULT_STRATEGIES`, and say in the
      mapping's comment that this is the third mode reaching that action and the
      first whose reason is convergence rather than removal.
- [x] 8.1a Add `tools/rollouts.py` to `agent_investigator`: the offer and the
      reader that serves it. No arguments, as the register channel takes none -
      the service is the incident's and there is nothing else for a model to
      name. It reports rather than raises, for the register's reason: a rollout
      nobody could read supports no conclusion either way, and ending the
      investigation over it would throw away everything already retrieved.
- [x] 8.1b Wire it through the layers a channel passes: a fetcher type in
      `retrieval.py`, a branch in `dispatch.py`, a place in `offer.py`, and the
      collaborator wherever the Investigator's are assembled. Not covered by
      registering the tool on the read tier - that makes the channel *available*,
      and this is what makes it offered.
- [x] 8.2 Tell the Investigator, in the standing brief, to read the rollout before
      attributing an incident to the revision that landed. This is the paragraph
      that makes the channel get used - the deploy history already names a
      revision, and a reader with an answer in hand does not go looking for
      another channel.
- [x] 8.3 Check what the narration says about a rollback, and leave it alone.
      This task asked for words about a rollback that converged a fleet rather
      than removing a revision, and writing them would have been wrong. The
      narration dispatches on the action kind and has no diagnosis in hand, which
      is not a limitation to route around: what happened is identical in all three
      modes - the deployment was returned to the revision it ran before - and the
      line already says exactly that and nothing about a revision being at fault.
      A sentence that varied with the mode would be the record asserting a verdict
      the action does not carry. The difference between the three lives in the
      account, which is the hypothesis's own words and the postmortem's.

## 9. Evidence

- [x] 9.1 Add the e2e case: seeded, diagnosed as an in-flight compatibility break,
      rolled back, confirmed, mitigated and not resolved. Propose the file; it is
      `tests/`.
- [x] 9.2 Add the withdrawal case beside the rollback's, the scale-out's and the
      pin's, off the same corpus: the rollback taken, the incident taken back
      mid-walk, and the fleet split again.
- [x] 9.3 Add the Investigator eval cases: the mode determined here, and
      `bad-deployment` still determined where the rollout converged. A matched
      pair, as the capacity pairs are - same alert, same stepped error rate, same
      single deploy entry at the onset, and the single variable is whether the
      rollout finished. Bars `UNMEASURED` until a paid run measures them.
- [x] 9.4 Everything free, green, before anything is recorded: `lint`,
      `typecheck`, every guard, `test_all`, `integration`, the demo app's own
      suite, `openspec validate --specs`, and a rehearsal through
      `scripts/seed_a_rehearsal.py`.
- [x] 9.4a `grade_fixes`, **after the re-record and not before it**. This task
      said it runs after 9.5 because it refuses a dirty tree; that is true and it
      is not the binding constraint. Two recorded fixes -
      `both-upstream-dependency-failure` and `both-pricing-service-degraded` -
      rewrite `src/io_shop/account_page.py` as whole files, authored against the
      shape of a summary-cache entry that the scenario's own commit changed.
      Applying either on top of the new shape reverts the read path and fails the
      test that commit added, so the grader is red for a reason that is the
      corpus's staleness rather than any fix being wrong. The demo app's suite is
      green at HEAD (63 passed) and red only with a stale patch written into it,
      which is what says so. Re-recording those two corpora is what clears it, so
      this runs with 9.7.
- [x] 9.4b Refuse a submitted file whose content is not source, found by 9.4a and
      fixed rather than recorded as known. The model wrote the new module into its
      explanation and put `(see above)` where the file's content belongs; the
      submission was schema-valid, nothing refused it, the walk finished looking
      like a success, and the grader found a shop that would not import.
      `_is_only_a_placeholder` names this case and declines it - "anything that
      will not parse is not judged here" - and nothing else judged it either. So
      Code-Fix now puts such a file back for another attempt, as it does an empty
      patch, and a model that never writes source runs out rather than proposing a
      branch nothing can read. Two tests, and the one corpus re-recorded against
      the fix.
- [x] 9.5 Push the demo app. Nothing that reads GitHub sees an unpushed commit,
      and the two revisions this scenario is built on are read from GitHub by both
      the diff channel and Code-Fix.
- [x] 9.6 One paid checkpoint, not one per step: record the new
      `both-half-finished-rollout` corpus and re-record every `both-*` corpus. A
      sixth channel moves the Investigator's tool list, which stales all of them -
      a larger invalidation than the seventh mode's meaning caused, and the reason
      this is the only paid step.
- [x] 9.7 `e2e_replay(mode='both')` green on the whole set afterwards. Report how
      many of how many, elapsed, and the token spend summed from the replay log
      before teardown.

## 10. The record

- [x] 10.1 `docs/failure-modes-backlog.md`: the tail/outlier row stops being
      "Partly" and becomes the third family covered entire; the FM-35 entry says
      what the scenario added beyond itself - the first mode with no culprit
      commit, the first channel that reads a deployment as a stretch rather than
      an instant, and a failing share that is a product of two shares.
- [x] 10.2 Rewrite "What is worth building next" so FM-35 is gone from it and a
      member of foundational integrity is first - the largest family with nothing
      built in it. A backlog that still names a built thing as next is a backlog
      nobody trusts.
- [x] 10.3 `docs/spec-and-architecture.md`: the sixth retrieval channel and the
      eighth mode, written as though the design had always said so.
- [x] 10.3a Record in the backlog that **a withdrawal only puts back the paused
      rollout**. `cache-misconfigured` and `bad-deployment` both say in their own
      descriptions that withdrawing the rollback brings the incident back, and
      neither does: `withdraw_the_rollback` reopens the rollout and leaves
      `cache_outage` and `deploy_slowdown` where the rollback left them. So two of
      the three rollback modes are mitigated and never un-mitigated, and both e2e
      withdrawal cases assert the incident's record instead of the world. The
      asymmetry is older than this change - the endpoint had no direction before
      it, so a withdrawal re-ran the rollback and put nothing back for any mode -
      and what this change did was give one mode a real answer, which is what made
      the gap visible. Record it as a defect with a shape rather than a note: the
      fix is two more branches in `withdraw_the_rollback` and two e2e withdrawal
      cases that read the world.
- [x] 10.4 Add to the backlog's "Measurements owed" what the irreversible-action
      question would buy, with this scenario as its motivation. Converging a
      rollout forward is the mitigation this change declined to build, and the
      reason - that an action which cannot be undone is not one Argus takes unasked
      - is worth finding written down the next time somebody proposes one.
