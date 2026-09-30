Every Argus-side item below is a TDD cycle: the test is proposed in chat, the
user pastes it, and the implementation follows it. `Argus-Demo-Target-App` is a
fixture and is covered after the fact, not before.

## 1. The shop goes dark while staying well

- [x] 1.1 Stop telemetry publishing from the minute a deployment lands, in
      `Argus-Demo-Target-App`: `/metrics` carries a row for every minute up to the
      revision and no row for any minute at or after it
- [x] 1.2 Keep `/logs` answering normally across the whole span, the dark minutes
      included - the shop serving well is the corroboration the whole diagnosis
      rests on, and a log channel that went quiet with the metrics would stage a
      service that is down
- [x] 1.3 Keep the shop genuinely well: orders succeed, the pages are right, and
      nothing in the process is affected by the revision beyond what it publishes
- [x] 1.4 Assert the absence is an absence - no row at or after the onset, rather
      than rows of zeros. A zero-valued bucket is a flat window, which is FM-26,
      and the mode evaporates
- [x] 1.5 Assert the quiet stretch before the revision is present and at baseline,
      since it is what makes the stopping legible and what `find_onset` reads
- [x] 1.6 Add the console entry under the existing foundational-integrity family
- [x] 1.7 Keep the reset restoring telemetry publishing, and check that a reset
      shop serves a whole window again

## 2. The absence alert

- [x] 2.1 Fire a `MetricsAbsent` alert in the existing Grafana shape, under its own
      rule name, from the same stand-in that fires every other alert
- [x] 2.2 Carry the first silent minute as the stated onset - the minute after
      the last sample, and the minute the revision landed in. Not the last
      sample's own minute: an onset carrying a bucket answers "the readings cover
      this incident", which bounds the change window at the onset and leaves the
      cause outside it
- [x] 2.3 Fire it materially after that minute, and assert the distance. This is
      what makes the mode diagnosable rather than only what makes the rule correct:
      nothing in front of the model says what time it is now, so the only handle it
      has on the gap is the alert's own firing time against the last row
- [x] 2.4 Check that a shop publishing normally fires nothing

## 3. The kernel's new word

- [x] 3.1 `FailureMode.MONITORING_BLIND_SPOT`, with the comment saying what
      separates it from the modes it shares an arrival and an action with - whether
      the service or the sight of it got worse
- [x] 3.2 Its `meaning()` entry, separating it from `feature-flag-toggle` and
      `bad-deployment` on that, and from `silent-data-corruption` on the rows being
      missing rather than present and flat

## 4. The opening message says the rows stop

- [x] 4.1 Measure the gap where the message is built - the last row's minute
      against the alert's firing time - the way `opened_already_elevated` is
      measured there rather than left to prose. A model cannot subtract two facts
      it was never both given
- [x] 4.2 Say in the onset paragraph that the rows stop, where they stop, and that
      their stopping is what the alert is about
- [x] 4.3 Rewrite the per-minute paragraph for the same window, in the same pass:
      it currently says the rows are what the service reported and that none of
      them departs, that there is no more of this channel to ask for, and that an
      empty *cell* is not a zero. All three mislead here
- [x] 4.4 Leave FM-26's flat-window wording byte-identical, and check a flat window
      still reads exactly as it did
- [x] 4.5 Check the measured-onset path is untouched

## 5. An absence narrated as an absence

- [x] 5.1 Say a metrics read whose rows stop as that rather than as a count of
      minutes, so the dashboard, Slack and the postmortem do not each report a
      short window
- [x] 5.2 Decide what the record underneath it should carry. `MetricsRetrieved`
      documents `window_end` as absent exactly when nothing came back; under
      truncation something did come back, so the field holds the last row's minute
      and nothing in the event says that minute was well before the alert fired.
      Either the event gains the fact or its docstring stops claiming to carry it -
      a field that has quietly become the wrong fact is worse than a missing one
- [x] 5.3 Whatever 5.2 decides, hold it for the replay row too, which has the same
      shape

## 6. Recovery is the read returning

- [x] 6.1 Separate the state `has_recovered_since` collapses: no minute at or after
      the moment asked about is not the same answer as minutes that are there and
      have not come back
- [x] 6.2 Judge a blind spot's recovery on the read returning, and state it as a
      rule about an incident whose minutes are absent rather than as a mapping from
      this mode
- [x] 6.3 Leave `anything_was_read` and the escalate-on-nothing-read branch alone.
      They are the last two sessions' work, they are about a read that *raised*,
      and nothing here raises
- [x] 6.4 Check a wrong candidate still refutes and the walk still reaches the next
      one - it does today, and 6.1 must not cost it
- [x] 6.5 Check a returned-but-unhealthy window no longer refutes a blind-spot fix
      that worked, which is the first of the two wrong answers the rule exists for
- [x] 6.6 Check every other mode's verdicts are unchanged

## 7. The walk

- [x] 7.1 Map `MONITORING_BLIND_SPOT` to the existing `RollBackDeployment` in
      `DEFAULT_STRATEGIES`. Required rather than optional: an unmapped mode answers
      `None` and escalates with no action for anything to judge
- [x] 7.2 Check no new node, refusal or status was needed, and that the only thing
      crossing an agent boundary is the minute the alert stated - a timestamp the
      incident arrived with, not a mode and not a judgement. `None` there is both
      "measured onset" and "nobody passed one", which is safe only while the walk
      binds `take_action` directly rather than through `mitigate()`; said beside
      the parameter, because that is the one way it fails quietly.
      Restart-is-refuted is asserted by `monitoring-blind-spot-scenario` and is not
      re-asserted here

## 7b. The gate stops refusing what it can confirm

- [x] 7b.1 `Findings` says whether any reading covers the minutes from the onset on.
      Measured in the Investigator, which is the only place holding both the onset
      and the window, and defaulted so every existing construction is unchanged
- [x] 7b.2 Carry it through the investigation node into the walk's state
- [x] 7b.3 Refuse an action as unconfirmable only where the incident was dated by
      the alert **and** the readings cover its minutes. One inference still, on two
      properties of the evidence and no mode
- [x] 7b.4 Check silent data corruption is still recommended and never taken - it
      is the reason the refusal exists and its window covers every minute
- [x] 7b.5 Check a blind spot reaches `take_action` at all, which is what makes
      section 6 reachable rather than theoretical

## 8. Proving it for free

- [x] 8.1 Drive the whole walk under the Anthropic double, so the paid run buys
      only the question of whether a model reads it. Driven by the flag walk's own
      recorded answers, which is enough for the path and nothing for the words:
      the double replays turns in sequence and never reads the tools' results, so
      a walk whose evidence changed underneath it still completes
- [x] 8.2 `e2e_replay(mode='both')` green across every existing scenario, before
      anything is recorded - the opening message is on a path all of them walk.
      40 of 40 in 31m23s, the blind-spot case among them: the rollback lands, the
      demo app ends the outage, and the rows come back
- [x] 8.3 `test_all`, `lint`, `typecheck`, `guard_layering` green

## 9. The paid run

- [x] 9.1 Push the demo app's revisions before anything reads them - Code-Fix reads
      GitHub, not disk
- [x] 9.2 `record(mode='both')` for `monitoring-blind-spot`, once 8 is green. 12
      recordings, five minutes, ending `mitigated` on a confirmed verdict
- [x] 9.3 Read the walk and answer the one question free runs cannot: does the
      model name the mode, or does it read a window that stops as a window that is
      short - and does it reach for the revision that landed after the last row,
      or discard it for arriving too late. It names the mode at 0.82 and names
      `metrics.portName` as its subject, so the change after the last row is not
      discarded for being late. The runner-up is `config-induced-failure` at 0.45
      on *the same subject* - which is the flag version's split repaired rather
      than merely moved: there the two candidates disagreed about what had
      changed and the leader had nothing to act on, and here they disagree only
      about which mode one agreed change is
- [x] 9.4 Report the token spend: 12 calls, 11,228 out, 126,772 cache read,
      52,804 cache write, 24 uncached in - about $0.63

## 11. The re-stage: a deployment rather than a flag

Nobody gates telemetry on a feature flag, and the split the flag version left in
the model's ranking survived the one fixture defect that could have explained it.
So the cause is a revision that renames the metrics port, and the answer is a
rollback. No flag version is kept.

- [x] 11.1 Stage it in `Argus-Demo-Target-App`: `ScrapeOutage` in `generator.py`,
      the scenario deploy-driven in `scenarios.py`, seed/window/rollback branches
      in `state.py`, and two revisions pushed - the `metrics.portName` block and
      the rename that reads as housekeeping
- [x] 11.2 `MONITORING_BLIND_SPOT` maps to `RollBackDeploymentStrategy`, and the
      flag handed in is not acted on
- [x] 11.3 The mode's `meaning()` says the two things the deploy staging makes
      load-bearing and the flag staging did not: that the change lands *after* the
      last row by construction, and that a service unchanged around it is what
      this mode predicts rather than evidence against the change
- [x] 11.4 `bad-deployment` names `monitoring-blind-spot` back. A revision at the
      onset is now the confusion this mode actually arrives in, and the deploy
      channel describes the two identically
- [x] 11.5 The e2e asserts a rollback of the service rather than a flag put back
- [x] 11.6 `scripts/record_incident.py`, the spec's mode table and the backlog all
      say a deployment. The backlog's FM-27 sibling becomes the version where the
      rename was deliberate and the answer is a fix rolled forward
- [x] 11.7 Delete the 17 recordings of the flag walk and record the deploy walk.
      They replayed green, which was the trap: the path was unchanged, so nothing
      failed - and the postmortem in the sixteenth still said the mitigation was
      reverting `monthly-spend-feature`, which no walk does any more. Twelve
      replace them, and `e2e_replay(mode='both')` is 40 of 40 in 32m21s against
      the new corpus

## 10. Evals and docs

- [x] 10.1 An Investigator eval case for the mode
- [x] 10.2 An eval case asserting a window whose rows stop under an absence alert
      is not read as a healthy service. Scored off 10.1's batch rather than a
      second one: the two are different claims about the same investigations, and
      the wrong answers differ - naming `bad-deployment` is a misread absence,
      naming nothing is an absence never looked at. So the second bar is 10 where
      the first is 9, and this is the one case here where abstention fails.
      Both bars are unmeasured, like every case added since the pools were taken
- [x] 10.3 `docs/failure-modes-backlog.md`: foundational integrity gains its third
      built member, FM-31 left as the family's last, and the deploy-caused sibling
      written down beside FM-26's
- [x] 10.4 `docs/spec-and-architecture.md`, as a specification rather than a
      changelog
