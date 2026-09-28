## 1. The autoscaler in the repository

- [x] 1.1 Add the `autoscaling` stanza to
      `Argus-Demo-Target-App/deploy/values-production.yaml`: a floor of three, a
      ceiling of six, a CPU target, and
      `behavior.scaleDown.stabilizationWindowSeconds: 0` - the field whose default
      of 300 exists to prevent thrashing, which is what makes this a real
      misconfiguration a reader can find and a patch could correct. Comment it as
      the file's other stanzas are commented: what the values are for, not that
      they are wrong.
- [x] 1.2 Read the stanza in `settings.py` beside `the_deployed_replica_count`,
      as the bounds the fixture's autoscaler is declared with. The live autoscaler
      is scenario state and this is where its *declared* shape comes from, which is
      the same split the replica count already has.
- [x] 1.3 Cover 1.2 in `tests/target_app/test_settings.py`, after the code.

## 2. The autoscaler as live state in the fixture

- [x] 2.1 Add the autoscaler to `ScenarioState` in
      `Argus-Demo-Target-App/src/target_app/state.py`, beside `syncs_itself` and
      the resize history: its floor, its ceiling, and a setter the platform
      stand-in's patch calls. Present only while the flapping scenario is staged -
      a live autoscaler under every scenario would scale the demand-saturation shop
      out on its own and destroy that scenario's grading.
- [x] 2.2 Answer `GET /argocd/{application}/resource` for a second kind. The route
      already ignores its selectors because there is one Deployment; it now reads
      `kind` and answers with the autoscaler's manifest for
      `autoscaling/v2 HorizontalPodAutoscaler` and the Deployment's otherwise. A
      404 where no autoscaler is staged, because a platform with no such resource
      has none to report and a fixture inventing bounds would let a pin be
      confirmed against a world that does not exist.
- [x] 2.3 Accept `POST` on that same path as Argo CD's `PatchResource` -
      **verified against the vendor's own swagger**: `resourceName`, `namespace`,
      `group`, `version`, `kind` and `patchType` as query parameters, and the patch
      as a **JSON-encoded string** in the body rather than an object. Apply a
      merge patch of `spec.minReplicas` and refuse anything else: a stand-in that
      answered 200 to a patch it did not apply would have a caller believe
      production had changed when it had not.
- [x] 2.4 Record the floor as a moment, not a value, for the reason a resize is
      one: from the instant it is set, every following minute is served at it, and
      minutes already served keep the capacity they were served at.
- [x] 2.5 Cover 2.1-2.4 in `tests/target_app/`, written after the code - the demo
      app's tests are a regression net, not a specification.

## 3. The cycle in the generator

- [x] 3.1 Derive the replica count for a minute from the cycle's position rather
      than from the resize history, for this scenario alone. A controller's resizes
      are not events anybody performed, and recording them as a window is served
      would make the same window read differently the second time it is fetched -
      the one property everything generated here rests on.
- [x] 3.2 Make the cycle three minutes: two served at three replicas, one served
      at six. The length comes from the lag new replicas take to become ready, so
      the minute after a scale-up is still served at the old capacity. Say that in
      the constant's comment - it is the real reason autoscalers thrash and the
      reason the cycle is not symmetric.
- [x] 3.3 Reuse `_SURGE_PEAK_MULTIPLE` and `_SURGE_RAMPS_OVER` rather than
      choosing new figures. 4.5x baseline over three replicas is already sized so
      that three are insufficient and six are comfortable, which is exactly the
      pair a flap needs, and a second multiple would need its own defence.
- [x] 3.4 Bound the derivation below by a floor in force, and stop the cycle at
      it. That is what makes a pin end the incident and what makes putting the
      floor back resume it.
- [x] 3.5 Let a replica count Argus sets directly be re-derived away by the next
      minute of the cycle. **This is the scenario's second point** and nothing in
      the fixture has ever done it: until now no controller put a count back, so
      the claim that a mitigation under a live controller has a timer on it was
      reasoned about and never demonstrated.
- [x] 3.6 Leave the error rate and the heap at their baselines, for the reason the
      surge leaves them there - errors are the leak's late signal and a climbing
      heap is the leak's signal entirely.
- [x] 3.7 Cover in `tests/target_app/`: the same window read twice is identical;
      capacity takes more than one value; usage pins in some minutes and not
      others; a direct scale is undone; a floor stops the cycle and putting it back
      resumes it.

## 4. The shape the detector needs

- [x] 4.1 Assert the cycle's arithmetic against the real detector, free, before
      anything else is built on it: departed minutes fall in runs of two separated
      by single clear ones, `find_onset` dates an onset at the first of the first
      pair, and `has_recovered_since` does **not** confirm over any stretch in
      which the cycle is still running. This is the task the scenario exists to
      satisfy and the one whose failure is silent - a symmetric cycle confirms the
      first action tried, whatever it was, and the wrong answer becomes
      accidentally right.
- [x] 4.2 Write the dependence on `anomaly_persistence_minutes` into the scenario
      spec's own requirement, so a reader of either one finds it. The shape works
      because that setting is 2; a deployment that changed it would break detection
      or grading with nothing failing.
- [x] 4.3 Propose the test for 4.1 - it is `tests/`, so it comes over as a whole
      file the human pastes.

## 5. The scenario

- [x] 5.1 Add `autoscaler-flapping` to `SCENARIOS` in `scenarios.py`: an
      `autoscaler_flaps` flag on `Scenario`, the title, and a description saying
      the traffic is the surge's, that nothing about the shop changed, that the
      deployment is a different size every minute, and that both a restart and a
      scale-out are undone.
- [x] 5.2 Add `autoscaler_flaps` to `stages_a_flag`'s exclusions, so nothing offers
      a flag as the thing that breaks it.
- [x] 5.3 Put it in the `CAPACITY` family, whose blurb already asks the question
      that separates its two members and now has a third - widen the blurb to say
      that a capacity which will not settle is a third answer, not a variant of
      either.
- [x] 5.4 Give it `HighLatency` on `io-shop` in `monitoring.py`, as the surge has:
      latency is the only judged series this incident moves, and without an alert
      rule nothing pages and no walk starts.
- [x] 5.5 Offer it in the console, under capacity. It is a scenario worth watching
      - the replica count moving on the page is the whole story - so unlike
      `monthly-statement-panel` it is not hidden.
- [x] 5.6 Confirm by hand: seed it, watch the capacity sawtooth and the quantiles
      oscillate; scale to six through the platform and watch the count come back;
      pin the floor and watch latency settle; restart and watch nothing change;
      put the floor back and watch it resume.

## 6. The mode

- [x] 6.1 Add `AUTOSCALING_PATHOLOGY` to `FailureMode`, with the maintainer's
      comment saying why it is not one mode with demand saturation: there a fixed
      capacity was outgrown, here the capacity will not settle, and the two are
      answered by opposite things - adding capacity, or stopping what keeps taking
      it away.
- [x] 6.2 Write its `meaning()` for the model reading evidence, not the maintainer.
      It must name the series that separates it from saturation - `cpu_limit_cores`
      taking more than one value across the window - because at the bottom of every
      cycle the rest of the evidence is saturation's exactly, so the distinction is
      a field to look at rather than a judgement to make.
- [x] 6.3 Widen `DEMAND_SATURATION`'s own meaning to point the other way, as the
      leak's does at saturation. A pair is only told apart if both halves say what
      the other one is.

## 7. The action and its undo

- [x] 7.1 Add `PinAutoscaler` to `action.py`: the application and no count, for
      the reason a scale-out carries none and one more - the count is not Argus's
      to choose even in principle, since the ceiling is a bound a human declared.
- [x] 7.2 Add `PIN_AUTOSCALER` to the union, to `ActionType`, and as a bare `Final`
      - bare so it infers its own single `Literal` and a match over the kinds stays
      checkable for exhaustiveness.
- [x] 7.3 Add it to `_LEAVE_SOMETHING_TO_PUT_BACK`. A floor raised is a change
      somebody could restore, and a row with no descriptor against it has to read
      as a change nobody accounted for.
- [x] 7.4 Answer for it in the three `match`es over the union in `action.py` -
      `the_subject_of`, `the_service_addressed_by` and `the_direction_of`. The
      application both times, and no direction: a floor is raised to a number
      rather than moved between two states.
- [x] 7.5 Add `AutoscalerUndo` to `undo_descriptor.py` - the application, the floor
      the autoscaler had, and whether the platform was reconciling it - with its
      `kind`, its tool constant and its place in the discriminated union.
- [x] 7.6 Add `AutoscalingRestored` beside `CapacityRestored`: the floor and the
      sync setting reported separately, because a restore can half-succeed and the
      half that fails is the quiet one.
- [x] 7.7 No migration. `action.action_type` is a text column with no check
      constraint, which is what lets a new kind arrive without one - confirm rather
      than assume.

## 8. The write tier

- [x] 8.1 Add `pinning.py` beside `scaling.py`: read the autoscaler's bounds from
      the live resource, suspend reconciliation if it is in force, patch
      `spec.minReplicas` up to the ceiling, and return the descriptor. Three
      requests for the reason the scale-out's are three, and the module docstring
      says which and why.
- [x] 8.2 Clamp the ceiling at `THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR` and import it
      from `scaling.py` rather than declaring a second figure. One estate, one bound
      on its capacity; two would be two numbers to keep level.
- [x] 8.3 Raise before touching anything where the floor already equals the
      ceiling. The count is not moving, so there is nothing to stop, and a caller
      told "done" would record a mitigation that never happened and then judge the
      service against it.
- [x] 8.4 Add `restore_autoscaler_floor`: the floor back first, reconciliation
      second, and a pair rather than an exception. Restoring sync first would have
      the platform set the floor back on its own, unverifiably, at a moment nothing
      here chose.
- [x] 8.5 Never restore reconciliation to a default - an application somebody had
      already stopped reconciling is left stopped.
- [x] 8.6 Name the wire vocabulary as `Final` constants at the top: the patch type
      (`application/merge-patch+json`), the resource's group, version and kind, and
      the field. And **URL-encode `patchType`** - a documented trap on this endpoint
      rather than a detail, and the thing the vendor's own issue tracker has people
      filing bugs about.
- [x] 8.7 Reuse `argocd_resource_path` for the patch: it is the same endpoint the
      resource is read from, and a second setting holding the same value would be a
      second place to correct when a deployment moves. **Take the namespace from the
      manifest the tier just read, and declare no setting for it.** This corrects
      what this task said before, which was to add `pin_namespace` beside
      `restart_namespace` and `scale_namespace` "following the precedent" - and
      following it was wrong. A pin has already read the resource it is about to
      patch, so a configured namespace is a second copy of a fact the platform
      stated a moment earlier, and the way it fails is silent: a patch addressed
      into the wrong namespace changes nothing and reports success. The restart's
      own setting stays, because a restart may be aimed at a dependency it never
      read and so has nothing in hand to take a namespace from. Unticked because
      `pin_namespace` landed in `config.py` and `.env.example` from the earlier
      wording and both need it removed.
- [x] 8.8 Register both tools on the server and add typed functions to
      `write_mcp_client`, as `scale_out` and `restore_replica_count` are.
- [x] 8.9 Update `.env.example` with the new namespace setting, and check no
      deployment config is relying on a code fallback for it.

## 9. Proposing it, and being allowed to

- [x] 9.1 Add `PinAutoscalerStrategy` to `strategies.py`. The application comes
      from the alert and from nowhere else - not from configuration, which would
      hardcode one estate's answer, and not from the hypothesis, whose subject is
      the model's description of what would not settle rather than an address.
      Always an action: a control loop the model found no words for is still a
      control loop on a deployment the alert names.
- [x] 9.2 Register it against `AUTOSCALING_PATHOLOGY` in `DEFAULT_STRATEGIES`, and
      say in the mapping's comment why this is the pair whose distinctions are
      load-bearing in the same direction the capacity pair's are: a reader who
      cannot tell a moving capacity from an outgrown one gets the mitigation the
      controller undoes.
- [x] 9.3 Add `PIN_AUTOSCALER` to `GENERIC_MITIGATIONS`. First mitigation that
      stops something rather than adding or restoring something, and the criterion
      is unchanged by that - membership of the set, never the kind of change.
- [x] 9.4 Add the protocols and the two functions to `agent_mitigation/tools.py`,
      as the scale-out's pair are.
- [x] 9.5 Answer for the action in both `match`es in `trying.py` - performing it,
      and the phrase a walk says about what it is about to try - and for the
      descriptor in `undoing.py` with a `_put_a_floor_back`.
- [x] 9.6 Add the `NOT_ATTEMPTED` cases to `test_trying.py`. Propose the file; it
      is `tests/`. Two of them, and the second is the half that matters: an
      exhausted action returns the new verdict, and a refusal carrying no
      `EXHAUSTED_ACTION_MARKER` still escalates - a `ScaleRefused` or `PinRefused`
      raised after reconciliation was suspended must not be read as "nothing left
      to do", which is what a single catch in the wrong order would do.
- [x] 9.7 Give the Investigator words for a pin among the attempts already tried.
      The fifth kind reaches `_what_was_done_in`, whose chain of comparisons ends
      in `assert_never` - so the missing branch does not read badly, it raises, and
      the investigation it raises in is the second round of a walk whose pin was
      refuted. Found by `typecheck` and by nothing else: every suite was green.

## 10. Saying what was done

- [x] 10.1 Words for a fifth action kind in `narrating.py`, and for its withdrawal.
      **A floor raised and a floor put back**, never a count set: two actions in
      this estate now decide how many replicas run, and a record that called them
      both scaling would leave a reader unable to say which owns the number.
- [x] 10.2 Name both floors in the line. The one it came from is what the
      descriptor records and what a reader needs to know was undone.

## 11. Scale-out's own delta

- [x] 11.1 State the general rule in `scaling.py`'s docstring and in the spec: it
      was never about git. Anything that re-derives the state a mitigation just set
      has to be suspended or changed before it is set, and a repository is one such
      thing.
- [x] 11.2 Leave a live autoscaler alone. A scale-out that suspended one would be
      one action silently becoming two, and it would be the wrong mode's answer
      arriving by the back door.
- [x] 11.3 Let the restore write the count it recorded even where the controller has
      since moved the live count away from it. The descriptor's job is to leave
      nothing Argus set behind, not to leave the deployment at a size Argus can
      vouch for.

## 12. Evidence

- [x] 12.1 Add the e2e case: seeded, diagnosed as autoscaling pathology, pinned,
      confirmed, mitigated and not resolved. Propose the file; it is `tests/`.
- [x] 12.1a Add the withdrawal case beside the rollback's and the scale-out's in
      `test_withdrawing_an_incident.py`, off the same corpus: a pin taken, the
      incident taken back mid-walk, and both pieces put back - the floor to what the
      autoscaler had and automated sync to how it was found.
- [x] 12.2 Add the Investigator eval cases: the mode determined here, and
      saturation still determined where the capacity held still. A matched pair, as
      the capacity pair already is - same alert, same latency climb, same empty
      change channels, and the single variable is whether `cpu_limit_cores` moved.
      Bars `UNMEASURED` until a paid run measures them.
- [x] 12.3 Everything free, green, before anything is recorded: `lint`,
      `typecheck`, every guard, `test_all`, `integration`, the demo app's own
      suite, `grade_fixes`, `openspec validate --specs`, and a rehearsal through
      `scripts/seed_a_rehearsal.py`. `grade_fixes` refuses a dirty
      `Argus-Demo-Target-App`, so it runs after 12.4.
- [x] 12.4 Push the demo app. Nothing that reads GitHub sees an unpushed commit,
      and a paid run against one buys a confident answer about the wrong tree.
- [x] 12.5 One paid checkpoint, not one per step: record the new
      `both-autoscaler-flapping` corpus and re-record the thirteen `both-*` corpora
      the seventh mode's meaning re-dated. Collect the new case under `both` alone,
      as the scale-out's and the large-fix's are - the claim does not vary by which
      tool found a file, and a corpus per mode is a walk per mode on every re-record
      for ever. Two things made them stale, not one: the seventh mode's meaning
      re-dated them, and the Investigator's brief gained the paragraph telling it to
      read `cpu_limit_cores` before naming saturation or a leak.
- [x] 12.5a Expect this to be the longest and dearest walk in the suite, and check
      before paying for it that it fits: the near-miss is a whole mitigation
      attempt - scale out, wait the verification timeout, be refuted, undo, try
      again - so budget for two attempts rather than one. If the recorded walk names
      the mode first time and never reaches the near-miss, say so rather than
      re-recording until it does; what the corpus holds is what happened.
- [x] 12.6 `e2e_replay(mode='both')` green on the whole set afterwards. Report how
      many of how many, elapsed, and the token spend summed from the replay log
      before teardown. 33 of 33 in 25:10, and nothing spent - every answer came
      from the committed corpus. It took three runs to get there: 29 of 33 in
      1:22:12, then 32 of 33 in 43:13, then green. Three of the four failures were
      the recovery rule this change introduced, which asked for a fixed number of
      clear minutes and so could not be satisfied by the one-minute question the
      e2e baseline assertion asks; the fourth was the memory case, whose corpus
      had stopped carrying a second candidate to reorder. The suite is 57 minutes
      faster than the first run, because a mitigation on a signal that never
      bounced is now confirmed on the first clear minute rather than the second.

## 13. The record

- [x] 13.1 `docs/failure-modes-backlog.md`: the capacity row stops being "Partly"
      and becomes the second family fully covered; the FM-25 entry says what the
      scenario added beyond itself - the first mode whose fault is a control loop,
      the first mitigation that stops something, and the first demonstration that a
      mitigation under a live controller has a timer on it.
- [x] 13.2 Rewrite "What is worth building next" so FM-35 is first and FM-25 is
      gone from it. A backlog that still names a built thing as next is a backlog
      nobody trusts.
- [x] 13.3 `docs/spec-and-architecture.md`: the fifth generic mitigation and the
      seventh mode, written as though the design had always said so.
- [x] 13.4 Add to the backlog's "Measurements owed" what a rate for this pair would
      buy, beside the saturation pair's - and note that the two pools are now one
      spend, since a paid Investigator run measures every bar in the suite.
