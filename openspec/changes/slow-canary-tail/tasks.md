## 1. The tail, as a number the shop reports

- [x] 1.1 Add `_BASELINE_P99_MS` to `generator.py` and report `p99_ms` on every
      `GeneratedMinute`, wobbling by the tail's own fraction, multiplied by the
      pressure curve and added to the provider wait exactly as `p95_ms` is.
      Drawn *after* the memory wobble, not beside the other two quantiles: each
      minute seeds one generator, so taking the draw in field order would have
      shifted memory in every scenario. Taken last, every existing figure is
      bit-identical
- [x] 1.2 Read the 99th percentile off the sample instead, for a minute whose
      requests carry measured latencies, by the rule `p50_ms` and `p95_ms`
      already use
- [x] 1.3 Serve it from `/metrics` and show it on the console, author it on the
      one scenario that is not generated, and cover 1.1-1.2 in the demo app's
      own suite (code first, tests after - the demo app is a fixture)
- [x] 1.3a Add the tail to `oncall._is_troubled`. An incident below the p95 and
      below the error rate bounded to no minutes at all, so the provider held no
      incident and every figure counted from person-minutes was counted over a
      night nobody was woken for
- [x] 1.4 Confirm every existing scenario's `p99_ms` tracks its `p95_ms`, and
      that no scenario's onset moves. The tail is a fifth signal, and a fifth
      signal that departs on its own noise would re-date four working scenarios
      - **folded into 2.5**, which is where the detector that reads it lives

## 2. Argus reads it

- [x] 2.1 Add `p99_ms` to `MetricBucket`, required rather than nullable - no
      deployment lacks a tail, and an absent one would be a missing measurement
      rather than a fact about the service
- [x] 2.2 Add the tail to the signals `argus_core.anomaly` judges departure on,
      beside `error_rate`, `p50_ms`, `p95_ms` and `memory_used_bytes`
- [x] 2.3 Add it to what `_minutes_still_at_the_incidents_level` judges
      subsidence on, so an incident found in the tail can only be confirmed
      recovered by the tail
- [x] 2.4 Add `p99_ms` to `argus_narration.BucketRow` and a tail column to
      `evidence.html` - the one column this incident is visible in is the one
      the page does not currently show
- [x] 2.5 Re-run the onset check over every scenario shape and confirm each is
      dated where it was. Measured over 60 independent windows each: the flag
      and provider scenarios date at the minute the condition began, the cache
      loss at its onset, the leak as a ramp. A calm 40-minute window reports an
      onset in 35 of 60 - **pre-existing and not the tail's doing**: blinding
      the tail to a flat series leaves it at exactly 35 of 60, so the other four
      signals produce it on the baseline's own noise. Nothing here changes it,
      and no staged scenario is affected, because `find_onset` takes the latest
      qualifying run and the real departure wins

## 3. The slow path, in the shop's own source

- [x] 3.1 Add `io_shop/typical_spend.py` - named for the figure rather than the
      `spend_breakdown` the proposal guessed at: a shopper's middle purchase,
      found by taking the cheapest that is left until the middle remains.
      Correct on every history the shop has, raising on none, and quadratic by
      the shape of the code rather than by a sleep, so a correct fix is a sort
- [x] 3.2 Have `io_shop/account_page.py` render through it when the request is
      one the rollout reached, told rather than deciding - the way it is already
      told `use_monthly_summary`
- [x] 3.3 Cover 3.1-3.2 in the demo app's own suite: the middle of an odd and an
      even history, a repeated price, and the case the figure exists for

## 4. Generating the incident

- [x] 4.1 Add `SlowRollout` to `generator.py` beside `CacheOutage`: when the
      rollout began, when it ended, and what share of a minute it was live for
- [x] 4.2 Route an exact count of the minute's sample to the slow path -
      `round(share × sample × share_of_minute)` - rather than drawing per
      request, and write the reason beside the constant: at three in a hundred
      of two hundred, a draw lands outside the band the scenario rests on about
      one minute in twenty-five
- [x] 4.3 Cost the slow path at the ordinary recompute multiplied by how much
      the shopper bought, so the cohort has a real internal spread and the
      slowest pages belong to the heaviest accounts. A page the rollout reached
      is also a cache miss by construction - the cache holds the figure the old
      rendering produced - which is what keeps the cohort on the expensive path
      instead of nine in ten of it being served fast
- [x] 4.4 Lift `the_working_cache_endpoint()` out of
      `roll_the_configuration_back` into `settings.py`, and have this scenario
      stage it with no outage
- [x] 4.5 Verify from generated buckets, over a window spanning the onset, that
      `error_rate`, `p50_ms`, `p95_ms` and `cache_hit_ratio` are flat and
      `p99_ms` departs by a multiple - and that this holds for *every* minute,
      which is what 4.2 is for. Measured over 560 incident minutes: p50
      unchanged, p95 median 189 -> 196 (a twentieth of the way to its departure
      bar, and inside the calm band's own 182-198 range - the cheapest canary
      pages belong to one-item shoppers and cost what a recompute costs), p99
      median 199 -> 1509, error rate unchanged, hit ratio down by the rollout's
      own share and inside its noise. The detector dated all 60 windows, 48 at
      the exact minute and 12 up to three minutes early, never late
- [x] 4.5a Weigh 4% against 3% and keep 3%. Four in a hundred shifts the p95
      median to 198 and puts 48% of incident minutes above the calm band, to fix
      a p99 that is merely weak (not flat) in under 1% of minutes. The p95 claim
      is the one the scenario cannot afford to soften
- [x] 4.6 Verify the rollout condition changes nothing for a scenario that does
      not stage one: each other scenario's figures identical with the condition
      absent, and each onset unmoved

## 5. Staging it

- [x] 5.1 Add `slow-canary-rollout` to `scenarios.py` - a generated flag
      scenario that recovers when the flag is reverted, staging the rollout and
      a healthy cache
- [x] 5.2 Wire it into `state.py`'s `seed`, `reset`, `phase` and
      `generated_window`, ending on the flag as the other flag scenarios do.
      Only `seed` needed anything: it is a flag scenario, so the other three
      already reach it by the path the first four take. The rollout itself is
      **not stored on the active scenario** - it is derived in `app.py` from the
      reconciled flag timeline, because it is that timeline said another way and
      a second record of one fact comes to disagree about when somebody reverted
- [x] 5.3 Add it to `_WHAT_FIRED` in `monitoring.py` with a `HighLatency` rule
      whose summary names the 99th percentile
- [x] 5.4 Confirm a restart does not end it, and that reverting the flag does -
      plus that a reset puts its flag back, which the leak and the
      misconfiguration have no flag to do

## 6. Proving it end to end

- [x] 6.1 Propose the e2e case in chat for the user to add - `tests/` is
      off-limits - staging the scenario and asserting the diagnosis, the flag
      revert, and the incident ending. The window is split on the tail itself,
      which is not circular: the claim is not that the tail moved but that
      wherever it moved, the median and the p95 did not follow. No other series
      in the window knows the incident happened, so there is nothing else to
      split on
- [x] 6.2 Run `lint`, `typecheck`, `guard_layering`, `guard_exports`,
      `guard_e2e_boundary` and `test_all` green, and the demo app's own suite.
      All green: typecheck over 478 files, layering 6/6 contracts kept,
      `test_all` 1285 passed in 3 minutes, and the demo app's own 255
- [x] 6.2a Preflight everything the paid run does not need a model for. The
      recording's name is in the e2e framework *and* in
      `scripts/record_incident.py` (a name the script does not know records
      nothing). The fixture image carries the new module - the `Dockerfile`
      copies `src/` wholesale, and nothing was added outside it, which is what
      bit the `deploy/` case. No new platform call: the flag revert is the one
      four scenarios already exercise. No new collaborator, so no `partial` at a
      composition root to leave half-bound
- [x] 6.2b Prove the case's own arithmetic against the *real* window shape, not
      the offline one. The fixture serves 90 minutes with the onset backdated by
      the configured 5, and a walk runs on top of that - so the affected stretch
      is neither a fixed length nor a fixed fraction. Over 160 windows spanning
      walk durations of 0 to 9 minutes: the detector found an onset in every
      one, dated at the first genuinely slow minute in 126 and at most two
      minutes early in the rest, and the e2e case's own assertion passed 160 of
      160
- [x] 6.2d **The scenario staged two faults, not one.** It leaves `flag_role`
      and `breaks_when_flag_is_on` at their defaults, so seeding it turns
      `monthly-spend-feature` on - which is also the switch for the existing
      `ZeroDivisionError` canary at `CANARY_SHARE`. Measured as `app.py` wires
      it: error rate 1% -> 4% median and 7.5% at worst, 397 minutes quoting
      `ZeroDivisionError`, and 72 of 440 incident minutes over the case's own 5%
      bar. It read as 4% rather than 32% because the working cache absorbs nine
      requests in ten before they reach the monthly path, which is why it was
      subtle.

      **The cause is a gap in the tests, not in the reasoning.** Every generator
      case in 4.5 passed `timeline=None` - the condition alone, never the
      arrangement it is served in. Task 6.2c, seeding against the running stack,
      was the unchecked item that would have caught it.

      Fixed by making the flag ship the typical-spend path instead of the
      monthly one while this scenario is staged. The canary is still drawn, so
      no figure moves in the four scenarios that do ship the monthly summary.
      Four new generator cases stage the flag and the rollout together, and two
      of them go red against the bug
- [x] 6.2e Re-establish the FM-06 premise on app-shaped windows, with a control.
      A detector with the tail blinded dates an onset inside the incident in 50
      of 160 - but a window with **nothing staged at all** does so in 68 of 160,
      so those 50 are the shop's own error-rate noise landing late by chance
      rather than the rollout leaking. Blaming each series in turn confirms it:
      all 50 are carried by the error rate, which is at its baseline. The
      premise holds
- [x] 6.2f Give the expensive path a cost floor of a recompute *plus* the
      per-item scans, which is what the code does - it collects the prices
      before it starts scanning. It does **not** remove the p95's 189 -> 196
      nudge: that is structural, since the requests the rollout takes are no
      longer cacheable and the 190th value sits higher in the same band of
      misses. Kept for faithfulness, and the comment says so rather than
      claiming a fix it did not make
- [x] 6.2c Seed `slow-canary-rollout` against the running stack and read
      `/metrics` from it - the one preflight item that needs the stack up, since
      staging a flag scenario reaches the provider. Verified by the replay run
      itself: the case's two novel assertions, `_only_the_tail_ever_moved` and
      `_no_request_ever_failed`, both passed against the live fixture. What
      failed were the four downstream of the missing recording - no hypothesis,
      still investigating, flag still on, and a shop still departing on error
      rate 0.01 and p95 198ms, which are both the baseline. It departs on the
      tail alone, which is the scenario stated by the detector itself
- [x] 6.2g `e2e_replay(mode='both')` over the other 23 cases: 22 passed, 1
      failed in 28:44, the failure being the new case with no recording yet.
      Superseded in part by 6.2h: a later run of the same suite failed the cache
      case as well, and that one was the detector rather than a missing file
- [x] 6.2h **The detector refused a mitigation that had worked.** The cache
      rollback case failed on `mitigated`, on the sync staying suspended and on
      a postmortem that never came, one run in five - and the same defect had
      already been measured in task 2.5 as 35 of 60 calm windows reporting a
      false onset, diagnosed there as pre-existing and written down as a reason
      to move on. It reproduces on a bare list of twelve numbers.

      `_departure_threshold`'s spread was one-sided by construction. The quiet
      stretch is the window's lowest half *by value*, so its 90th percentile is
      about the 45th of the series and the distance from there to the 25th never
      looks at an ordinary minute. On a rate quantised into half-percent steps
      that difference is one step or exactly zero, so the bar sat a few
      thousandths above a baseline calm minutes clear five times over - and the
      error rate, which never moves in that scenario at all, read as still
      elevated on every minute after the rollback.

      Three changes, each earning its place. `_subsided_threshold` returns `inf`
      for a series that never reached the incident level rather than flooring at
      the departure bar - a real invariant, and on its own it fixed nothing,
      because the error rate's own noise exceeded its own departure bar. The
      spread moved onto `_CalmStretch` beside the floor it already carried, so
      the value-ordered half reads its **range** while the opening keeps its
      quantile. And a floor at twice the quiet stretch's own quantisation step.

      | | before | after |
      |---|---|---|
      | rolled-back cache windows refusing recovery | 11/40 | 0/40 |
      | calm 8-min windows, false onset | 75/200 | 15/200 |
      | calm 12-min windows, false onset | 118/200 | 6/200 |
      | calm 90-min windows, false onset | 92/160 | 2/160 |
      | flag / provider / cache / leak / rollout onsets | all found | all found |
- [x] 6.2i Give the detector fixtures a calm window a service could actually
      report. Every calm fixture in `test_anomaly.py` was a constant, which is
      the one input the spread's floors were built for, so the whole class of
      defect above was unreachable from the suite that owns it.
      `argus_core_test.framework.windows` builds the other kind - an error rate
      counted over a sample of two hundred, so quantised by construction, and
      three quantiles read off a two-path mixture - seeded, so a failure
      reproduces exactly.

      Two arrangements the existing tests state and cannot stage: a quiet
      stretch with no incident behind it, where `find_onset`'s latest-run rule
      cannot discard a false onset before anyone sees it; and a lone noisy
      minute landing **last**, which is every poll of a growing mitigation
      window. The second went red. `_departs_for_long_enough_to_be_the_incident`
      credited a run still going when the window ended - right for an onset,
      inverted for recovery - so one noisy sample denied a verdict every minute
      before it supported, and waiting could not clear it. Recovery now requires
      the run to persist, and `_stays_clear_of_the_incident` refuses a stretch in
      which no minute has fallen clear at all, which is the service not having
      answered yet rather than a service that came back
- [x] 6.3 Record the scenario's model answers against the real API under each
      `CODE_SEARCH` mode, and commit the recordings - **the paid step**. Both
      modes succeeded in 4 minutes each, and the model reached the same place
      each time: a flat error rate, a flat median, a flat p95 and a tail at ten
      times its baseline read as a flag toggle, the flag went back, and the shop
      returned to baseline. That was the one thing preflight could not prove and
      the thinnest evidence any case here offers
- [x] 6.4 Run `e2e_replay(mode='both')` green, and report the token spend from
      the recording run. 23 of 23 passed in 20:44, on a stack carrying the
      detector as 6.2h and 6.2i left it - which is what the run was for: the
      previous one predates both, and the cache case it failed on is the defect
      6.2h fixed. Spend, 19 recordings over two incidents: 17,908 output, 38
      uncached input, 108,163 cache reads, 69,635 cache writes
- [x] 6.5 Update `docs/failure-modes-backlog.md`: FM-06 is built, and what it
      added beyond the scenario
- [x] 6.6 Update `docs/spec-and-architecture.md` as a specification - five
      signals rather than four, described as though always intended. The
      benchmark suite's scenario list gained the tail scenario, and the cache
      misconfiguration it had been missing since that change landed
