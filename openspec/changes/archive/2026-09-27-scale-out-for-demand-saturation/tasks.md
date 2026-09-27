## 1. Capacity as state in the fixture

- [x] 1.1 Add the replica count to `ScenarioState` in
      `Argus-Demo-Target-App/src/target_app/state.py`, beside `syncs_itself` and
      the deploy revision, with a setter the platform stand-in calls and a reset to
      the values file's three. It is the scenario's live condition, so it belongs
      where the other live conditions are. **A history of resizes rather than a
      count** - the fixture caches each finished minute on everything it is
      computed from, so a scalar would regenerate the already-served minutes at the
      new size and take the incident out of the window the moment it was
      mitigated.
- [x] 1.2 Accept Argo CD's built-in `scale` action in `argocd_run_resource_action`
      (`app.py`), beside `restart`. The action name and the `replicas` parameter
      are the vendor's - a *string* on the wire, per the action's own tests - so
      the stand-in parses it and refuses a non-number the way the real action
      errors.
- [x] 1.3 Report the count where a caller reading the live resource would find it,
      so the write tier can read what is running rather than what git holds. One
      endpoint, shaped like the platform's own.
- [x] 1.4 Cover 1.1-1.3 in `tests/target_app/`, written after the code - the demo
      app's tests are a regression net, not a specification.

## 2. CPU in the generator

- [x] 2.1 Add the CPU pair to `GeneratedMinute` and to the metrics the endpoint
      serves: `cpu_used_cores` and `cpu_limit_cores`, capacity being the
      deployment's total across the live replica count.
- [x] 2.2 Compute demand from the minute's reported volume against a per-replica
      throughput constant, and report usage **clamped** at capacity while the
      latency multiple is taken from unclamped demand. A saturated gauge that
      stops rising while latency does not is the signature; a gauge growing past
      its ceiling is not a thing a real one does.
- [x] 2.3 Aggregate usage as the minute's mean, not its maximum, and say why in
      the constant's comment: a heap's peak is what breaches a limit, where a
      second at full CPU is what an ordinary busy minute contains. A maximum
      reports every minute as saturated.
- [x] 2.4 Give the quiet minutes a CPU baseline with its own wobble, so the series
      has a baseline to have departed from - the reason the tail and the hit ratio
      are on every bucket whether or not a scenario is about them.
- [x] 2.5 Cover the clamp, the mean and the capacity moving with the replica count
      in `tests/target_app/`.

## 3. The scenario

- [x] 3.1 Add `cpu-saturation` to `SCENARIOS` in `scenarios.py`: a `surges` flag
      on `Scenario`, the title, and a description saying what the load did, what
      the shop did about it, and that nothing was deployed and no flag moved.
- [x] 3.2 Ramp the reported volume from the baseline over the first minutes to a
      multiple that one doubling of the replica count clears, then hold. Sized so
      the two-attempt path is possible rather than required (design's own bound).
- [x] 3.3 Leave the error rate and the heap at their baselines. Errors are the
      leak's late signal and a climbing heap is the leak's signal entirely;
      borrowing either blurs the one distinction the scenario exists to draw.
- [x] 3.4 Add `surges` to `stages_a_flag`'s exclusions, so nothing offers a flag
      as the thing that breaks it.
- [x] 3.5 Give the scenario its alert rule in `monitoring.py`: `HighLatency` on
      `io-shop`, since latency is the only judged series this incident moves.
      Without it nothing pages and the walk never starts.
- [x] 3.6 Confirm by hand: seed it, watch the quantiles climb and the gauge pin;
      scale to six through the platform and watch latency come back; restart and
      watch nothing change but the start time. Driven over HTTP against the
      fixture's own stack rather than through the browser - the console's
      rendering is the one part still unlooked-at. What it showed: volume ramps
      1200 to 5400 and holds, CPU pins at 3.00/3.0, p50 goes 46ms to ~365ms with
      p95 and p99 climbing with it, and the error rate and the heap never stir. A
      restart moved the process start time and nothing else - same quantiles, same
      pinned gauge - and the minutes before it kept the process that served them.
      A scale to six raised capacity to 6.0, unpinned usage at 3.25, and put every
      quantile back at baseline with the traffic still at 5400, while the
      saturated minutes stayed in the window.
- [x] 3.7 Cover the scenario's shape in `tests/target_app/` - the quantiles moving
      together, the error rate and heap flat, recovery on a raised count, and a
      restart changing only the start time.

## 4. The bucket

- [x] 4.1 Propose the test for the two new fields on `MetricBucket` in
      `modules/argus_core/tests/argus_core_test/models/`: usage required, capacity
      nullable, and a bucket that omits the capacity still valid.
- [x] 4.2 Add `cpu_used_cores: float` and `cpu_limit_cores: float | None` to
      `metrics.py`, with each gauge's aggregation rule in the docstring beside the
      existing three - including why this one's rule differs from memory's.
- [x] 4.3 Carry the pair through to the model. It needs no code: the read tier
      passes whole buckets and `agent_investigator/tools/metrics.py` dumps them
      field-for-field. Covered by the case that pins the per-minute CSV the model
      reads, which now carries both columns - a test of this claim that already
      existed, rather than a new one.
- [x] 4.4 Say CPU in `argus_narration/metrics.py`, beside `_memory_said`: usage
      against capacity in cores, and the saturated case said as saturation rather
      than as two numbers a reader has to divide.

## 5. The detector does not judge it

- [x] 5.1 Propose the tests in `argus_core_test`: a window whose CPU departs while
      the five judged series do not dates no onset; a window where CPU pins two
      minutes before the quantiles climb dates the onset at the quantiles; and a
      recovery is not held open by CPU still being high.
- [x] 5.2 Confirm `anomaly.py` needs no change to satisfy them, and say in the
      module's own words that CPU is retrieved and not judged - beside
      `request_volume`, which the departure floor already refuses to read.

## 6. The mode

- [x] 6.1 Propose the test for a sixth `FailureMode` and its meaning in
      `argus_core_test/models/test_failure_mode.py`.
- [x] 6.2 Add `DEMAND_SATURATION = "demand-saturation"` with the comment the set's
      maintainer reads, and its entry in `_WHAT_EACH_MODE_MEANS` - which says what
      separates it from a leak (the consumption moved *with* the traffic) and from
      a deployment and a dependency (nothing changed, and the time is spent in the
      service's own work).
- [x] 6.3 Check `BRIEF` in `agent_investigator`: the mode list travels in the tool
      schema, so the brief needs changing only where it counts the modes or names
      the ways evidence is read.

## 7. The action and its undo

- [x] 7.1 Propose the tests for `ScaleOut` and `ReplicaUndo` in
      `argus_core_test/models/`: the action carries the application and no count;
      the kind leaves something to put back; the descriptor carries the prior
      count and the prior sync policy; and the four functions over the union all
      answer for it.
- [x] 7.2 Add `ScaleOut` to `action.py` - the union member, the `SCALE_OUT` tag,
      the `ActionType` literal, membership of `_LEAVE_SOMETHING_TO_PUT_BACK`, and
      the branches `the_subject_of`, `the_service_addressed_by`,
      `the_direction_of` and the identity stop compiling without.
- [x] 7.3 Add `ReplicaUndo` to `undo_descriptor.py` with its `kind`, its
      `was_replicas`, its `was_syncing_itself` and the tool constant, and put it in
      the `UndoDescriptor` union.

## 8. The write tier

- [x] 8.1 Propose the tests for `write_mcp_server/scaling.py`: the count read
      before the action, the double, the clamp at the ceiling, a refusal at the
      ceiling, automated sync suspended first and recorded as found, and an
      application already not reconciling left that way.
- [x] 8.2 Add `scaling.py` beside `rolling_back.py`, reusing its sync-suspension
      path rather than copying it. The target count is the tier's to resolve, and
      the result reports the count that was running and the count now.
- [x] 8.3 Hold the ceiling in the tier as a constant, with the open question
      recorded in the design: configuration is what a second deployment would
      want, and there is one.
- [x] 8.4 Register the tool in `server.py` and add the typed function to
      `write_mcp_client`, with the undo descriptor in its answer.
- [x] 8.5 Propose the test for the undo path, then teach it `ReplicaUndo` -
      restoring both pieces, and reporting a half-restore as the rollback's does.
- [x] 8.6 Green on `test_module` for `write_mcp_server` and `write_mcp_client`.

## 9. Proposing it, and being allowed to

- [x] 9.1 Propose the tests in `agent_mitigation_test`: the mode maps to a
      scale-out, a leak still maps to a restart, and the strategy reads neither
      the hypothesis nor the flag changes for its subject.
- [x] 9.2 Add `ScaleOutStrategy` to `strategies.py` - the service from the alert,
      for the reason the restart's and the rollback's come from there - and its
      entry in `DEFAULT_STRATEGIES`.
- [x] 9.3 Propose the test that the gate admits the kind, then add `SCALE_OUT` to
      the pre-authorised set. The set's criterion is membership, not
      reversibility; this one happens to be reversible anyway.
- [x] 9.4 Propose the test for the ceiling's refusal reaching the walk as a
      refusal in its own words rather than as an escalation with no reason.
- [x] 9.5 Green on `test_module` for `agent_mitigation` and `orchestrator`.

## 10. Saying what was done

- [x] 10.1 Propose the tests for the fourth action kind, each in the suite whose
      words it is about: the scale said when it is taken and said as a gerund
      where a line talks about it without it having happened here, in
      `argus_narration_test`; the withdrawal saying the count and the
      reconciliation both went back, in `agent_mitigation_test/test_undoing.py`,
      which is where those words are written; and a scale-out already tried
      described to the model as one, in `agent_investigator_test`. Not "with both
      counts": `ActionTaken` carries no number and `VerdictReached` carries no
      detail, so the count the tier reported is quoted in the verdict's own
      account and nowhere a narrated line can reach it.
- [x] 10.2 Add the words. One line per event, as every other kind gets.
- [x] 10.3 Confirm the dashboard and the postmortem need nothing of their own -
      both read narrated events, and a fourth kind they cannot say would have
      failed 10.1.

## 11. No patch for a capacity shortfall

- [x] 11.1 Confirm the walk already answers a mode with no code fix, using
      `internal-dependency-failure` as the precedent, and that what it records is
      "not warranted" rather than an unanswered request. It does, and the answer
      is mode-agnostic: `fixing.py` asks the agent whatever the walk concluded,
      and an agent offering no patch is published as `NOT_WARRANTED` - a verdict
      on the code, told apart from `NOT_ANSWERED` and `NOT_POSSIBLE` by the
      outcome rather than by the absence of a proposal. Pinned by
      `orchestrator_test/walk/test_fixing.py`'s not-warranted case.
- [x] 11.2 If it does not, propose the test first - this is a claim about the
      record, and the record is what a postmortem reads. Not needed: 11.1 holds
      and is already covered.

## 12. Evidence

- [x] 12.1 Add the e2e case for the scenario: seeded, diagnosed as demand
      saturation, scaled out, confirmed, mitigated and not resolved. Propose the
      file; it is `tests/`. The withdrawal is a case of its own rather than the
      tail of this one - a withdrawn walk ends `withdrawn` and never reaches a
      verdict - so it goes beside the rollback's in
      `test_withdrawing_an_incident.py`, off the same corpus.
- [x] 12.1a Add that withdrawal case: a scale-out taken, the incident taken back
      mid-walk, and both pieces put back - the count to what was running and
      automated sync to how it was found.
- [x] 12.2 Add the Investigator eval cases: the mode determined here, and a leak
      still determined where the traffic did not move. Bars written as
      `UNMEASURED` until a paid run measures them. A matched pair, as the
      deployment pair is: same alert, same latency climb, same log lines, nothing
      changed in either, and the single variable is whether the consumption moved
      with the traffic. `a_bucket_at` grew the traffic and the CPU as parameters
      to state it - every other case leaves both where they were.
- [x] 12.3 Everything free, green, before anything is recorded:
      `lint`, `typecheck`, every guard, `test_all`, `integration`, the demo app's
      own suite, `grade_fixes`, and `openspec validate --specs`. Two were red and
      both are settled: `guard_exports` named three exports of `agent_mitigation`
      that nothing outside the package imports any more - fallout from the seam
      split, since `performing_writes_over` and `an_undo_over` are what callers
      reach for now - and they are dropped from the export list; and `grade_fixes`
      refuses to run over a dirty `Argus-Demo-Target-App`, so it ran after 12.4
      and passed 11 of 11.
- [x] 12.4 Push the demo app. Nothing that reads GitHub sees an unpushed commit,
      and a paid run against one buys a confident answer about the wrong tree.
- [x] 12.5 One paid checkpoint, not one per step: record the new `both-cpu-saturation`
      corpus and re-record the twelve `both-*` corpora the new field and the sixth
      mode re-dated. All thirteen are captured. The eval is **deliberately not
      run**: a walk costs about $5 of the user's own money, the bars are written
      as `UNMEASURED`, and every other bar in that suite is stale for the same
      prompt change - so one more unmeasured pair changes nothing anybody could
      conclude. It keeps until there is a reason to spend on it.
- [x] 12.5a Two things the recording found, both fixed here. `monthly-statement-panel`
      escalated and was refused: memory from an earlier walk in the same run
      demoted its correct leading candidate, so the walk rolled back a scenario
      that stages no deploy. `record_incident.py` now drops long-term memory
      between names, as the e2e suite's teardown already did - the step its own
      docstring claimed to mirror. And a `grep` capture of `cpu-saturation` read
      to its **token** bound without answering: the last-call warning existed but
      fired on the call bound alone, so an agent whose answers are whole files was
      never warned. `Budget.is_on_its_last_call` now also fires when another turn
      the size of the dearest one so far would not fit.
- [x] 12.5b The scale-out case is collected under `both` alone, as the large-fix
      case is: its claim does not vary by which tool found a file, and a corpus
      per mode is a walk per mode on every re-record for ever.
- [x] 12.6 `e2e_replay(mode='both')` green on the whole set afterwards: 28 of 28
      in 23m20s, which is every corpus recorded here replaying, the new case
      against its real recording rather than the fabricated one, and the new
      withdrawal case beside the rollback's. The eval bars are **not** written
      from what was measured, because nothing was measured: the run is skipped by
      decision (12.5), so both stay `UNMEASURED` and a failure there reads as
      unmeasured rather than as a regression. What the spend would buy is written
      down in the backlog's "measurements owed" instead of left as an intention.

## 13. The record

- [x] 13.1 `docs/failure-modes-backlog.md`: the capacity row stops being "Partly",
      FM-13 is built in both halves, and the demand-saturation entry says what the
      scenario added beyond itself - the first mitigation that adds capacity, and
      the first bound on how far one may go. The row stays **Partly**: FM-13 is
      built in both halves, and FM-25 is the other mode in that family.
- [x] 13.2 `docs/spec-and-architecture.md`: the fourth generic mitigation, the
      sixth mode and the bucket's new pair, written as though the design had always
      said so.
- [x] 13.3 Note in the backlog that FM-25 is now unblocked - a replica count
      exists, is visible and can be changed - and that it is the next thing rather
      than the thing behind this.
