## Why

FM-27 monitoring blind spot is the largest unbuilt mode left in foundational
integrity (12%), the family whose other two members - FM-26 and FM-30 - are
built. It is the first mode in which **Argus's own evidence is the thing that
broke.** Every incident so far hands Argus a series and asks what it means; this
one hands it a series that stops, and asks it not to conclude the service is well.

It is also the mode the last two sessions prepared for without staging. The class
those commits closed is *a read Argus could not take was treated as a fact about
the service* - closed everywhere a walk whose reads worked could reach it. Here
nothing fails: the read succeeds, validates, and is narrated as a read that
happened. The absence is indistinguishable from health at every layer, and the
only thing between it and "we looked, the shop is fine" is prose in an opening
message. So the mode is the test of whether that work was a fix or a set of fixes.

## What Changes

- **`FailureMode.MONITORING_BLIND_SPOT`** - a tenth mode. What is wrong is
  neither the service's availability, its speed, its capacity nor what it has
  written, but the ability to observe any of them. The service is well
  throughout, nothing it does is affected, and the incident is entirely on the
  observer's side of the wire. It is the first mode whose correct reading of the
  evidence is *I cannot see*, and the first whose subject is the monitoring
  rather than the thing monitored.

- **A `MetricsAbsent` alert, and the scenario behind it.** A flag turns off the
  shop's telemetry publishing. The shop goes on serving - orders succeed, the
  pages are right, the logs keep flowing across every minute - and `GET /metrics`
  carries rows up to the minute the flag moved and **no row for any minute at or
  after it**. The rule that fires is the one every monitoring stack has for this
  and no scenario here has used: an absence held long enough not to be a scrape
  that was missed.

- **The window is truncated, not empty, and that is what the alert means.** An
  absence rule fires because a series that *was* reporting stopped; a window with
  no rows at all would describe a service nobody ever instrumented. So the quiet
  stretch before the onset is present and is what makes the stopping legible -
  and it is also the trap, because rows that simply stop read as a short window
  rather than as a service going dark.

- **The alert states the onset, and nothing new is needed to accept it.** What an
  absence rule knows is the first minute no sample arrived for, which is the
  onset exactly - so the alert carries it in `stated_onset` and the machinery FM-26
  built answers this mode unchanged. A measured onset is impossible here by
  construction rather than by accident: the rows that would carry a departure are
  the ones that are missing.

- **Two paragraphs in the opening message stop being true, and both are fixed in
  one pass.** The onset paragraph says *no series departs from its baseline
  anywhere in the window below*; the per-minute paragraph says *these are what the
  service reported around the alert, and none of them departs from its baseline*,
  that *they are the whole span the metrics source keeps - there is no more of
  this channel to ask for*, and that an empty **cell** is not a reading of zero.
  Over a window that stops at the onset, the first two are vacuously true of the
  rows that are there and say nothing about the minutes that are not; the third
  tells the model not to re-ask the one channel whose return is the recovery
  signal; the fourth arms a distinction about cells at a model facing missing
  rows. Both paragraphs say instead that the rows stop, where they stop, and that
  their stopping is what the alert is about.

- **Where the incident is that the service could not be read, the recovery is the
  read returning - judged as that, never inferred from the absence of a
  departure.** The mode already reaches the right verdicts, and that is the
  problem rather than the reassurance: a wrong candidate leaves nothing at or
  after the onset, `has_recovered_since` answers `False`, and the deadline refutes
  it; the right candidate brings the rows back, the window has no departure
  anywhere in it, and the no-departure clause counts every minute as recovered and
  confirms.

  So the confirmation of a blind-spot fix rests on *no series departed* - the
  exact inference the opening message is being changed to stop the model making,
  one layer down and unguarded. Two consequences, neither an edge case: a window
  that returns and is genuinely unhealthy for an unrelated reason refutes a fix
  that worked, because the sight came back and the rule was asked about levels;
  and nothing separates telemetry that returned because Argus reverted the flag
  from telemetry that returned on its own.

  The distinction needed is one `has_recovered_since` already draws and discards.
  *No bucket at or after the minute* and *buckets there, still at the incident's
  level* are two states with one answer today, and they are the difference between
  "the sight has not returned" and "the service has not recovered". Nothing is
  threaded from the Investigator to say so: the verification re-reads the same
  channel every pass and the fact is in the reading it already has.

- **An absence is narrated as an absence.** `MetricsRetrieved` renders today as
  "Read back N minutes of metrics" - a true count of the minutes before the
  incident, with nothing saying the rows stopped, in the three places that tell
  the incident's story.

- **The flag version first; the deploy version named as its sibling.** As FM-26
  chose, and for the same reason: a flag is reversible in seconds and a
  deployment that dropped its instrumentation is a fix rolled forward.

- **A blind spot is not answered by restarting the shop, and the scenario makes
  that refutable.** A restart changes nothing - the flag is still off and the
  minutes still missing - so an agent that reaches for the process learns the
  ordinary lesson and still has somewhere to go.

- **No sixth retrieval channel, so every recording stays valid.** The absence
  arrives in the read Argus already takes, the corroboration is in the logs
  channel it already has, and the cause is in the flag history it already reads.

## Capabilities

### New Capabilities

- `monitoring-blind-spot-scenario`: the Target Service serving normally while
  publishing no telemetry - which minutes `/metrics` carries and which it does
  not, what `/logs` goes on answering across the same span, why the rule is an
  absence rather than a threshold, why the alert carries the last sample's
  minute, why a restart is refuted, and what a reset restores.
- `unreadable-service-recovery`: the rule that where an incident is the service
  being unreadable, the recovery is the read returning and is judged as that -
  and that a window carrying nothing at or after the minute in question is a
  state of its own, distinct from one carrying minutes that have not recovered.

### Modified Capabilities

- `investigator-cause-detection`: monitoring blind spot is a determinable mode,
  and the requirement says what evidence names it - an alert whose subject is an
  absence, a metrics window whose rows stop at the stated onset, a logs channel
  answering normally across the same minutes, and a change at that minute.
- `alert-supplied-onset`: an alert may state the onset of an absence, and the
  opening message distinguishes a window that was read throughout from one whose
  rows stop. The existing flat-window wording is kept for the case it was written
  for.
- `flag-revert-mitigation`: its "verdict is measured from re-queried metrics"
  requirement gains the case where the minutes being judged are absent rather
  than elevated, deferring to `unreadable-service-recovery` rather than
  restating it.
- `incident-event-stream`: a metrics read whose rows stop is said as that rather
  than as a count, so the dashboard, Slack and the postmortem do not each report
  a short window.
- `unverifiable-action-recommendation`: an alert-stated onset stops being the whole
  of what makes an action unconfirmable. It is unconfirmable where the readings
  already cover the incident's minutes and *not* where those minutes carry no
  reading, because a channel can be watched coming back by a reading existing as
  well as by a level falling - and whether they cover it travels on the findings,
  since the gate holds the onset and never the window.
- `target-service-scenario-control`: the scenario is seedable and resettable like
  the others, and its reset restores telemetry publishing.

## Impact

- `argus_core.models`: `FailureMode` a tenth value and its `meaning()` entry -
  which has two neighbours to separate rather than one. Against
  `feature-flag-toggle` and `bad-deployment`, whose arrival and whose action are
  both identical, what differs is whether the service or the sight of it got
  worse. Against `silent-data-corruption`, which also says the metrics carry
  nothing: there every minute is present and sitting at baseline, here the
  minutes are missing.
- `argus_core.anomaly`: the state `has_recovered_since` currently collapses -
  nothing at or after the minute, versus minutes that have not come back.
- `agent_investigator`: the two opening-message paragraphs. The onset path, the
  tool list and the dispatcher are untouched.
- `agent_mitigation`: the verification's judgement for a window whose minutes are
  absent, and `MONITORING_BLIND_SPOT` mapped to the existing `RevertFeatureFlag`
  in `DEFAULT_STRATEGIES`. The mapping is required rather than optional: an
  unmapped mode answers `None` and escalates with no action for anything to
  judge.
- `orchestrator`: no new node, no new refusal, no new status, and nothing
  threaded between nodes. The walk this mode takes is the walk a flag-caused
  incident already takes.
- `argus_narration`: `MetricsRetrieved` said as rows that stop rather than as a
  count - one line, reaching the dashboard, Slack and the postmortem at once.
- `argus_web`, `agent_postmortem`: the mode shown and written up, including what
  is owed afterwards - an instrumentation gap and the alert rule that found it,
  rather than a defect in the shop.
- `Argus-Demo-Target-App`: the scenario; the flag state that silences telemetry
  publishing while the shop stays well; the absence alert and its name; the
  console entry under the foundational-integrity family the rail already has.
- Recordings: one new `both-monitoring-blind-spot` corpus. Every existing corpus
  stays valid, because no tool is added.
- Evals: an Investigator case for the new mode, and a case asserting that a
  window whose rows stop under an absence alert is not read as a healthy service.
- `docs/failure-modes-backlog.md`: foundational integrity gains its third built
  member, and FM-31 is left as the family's last.
