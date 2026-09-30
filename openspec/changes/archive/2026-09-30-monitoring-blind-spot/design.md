## What changed after this was written

The cause was re-staged mid-change, from a feature flag that stopped the shop
publishing to **a deployment that renames the port its metrics are served on**,
answered by a rollback rather than a revert. No flag version is kept. The
argument below for staging it behind a flag is the reasoning as it stood, and
two things overturned it.

Nobody gates telemetry on a feature flag. The flag version bought reversibility
in seconds at the cost of an incident no operator has ever seen, and the whole
point of the scenario is a change that looks like housekeeping and is not.

And the split it produced did not come from the fixture. A paid walk ranked the
mode at 0.78 with `feature-flag-toggle` second at 0.25 and no subject the leader
could act on; the one fixture defect that could have explained it - an audit
entry backdated differently from the onset - was fixed, the walk re-run, and the
split survived unchanged. Under the deployment the model ranks the mode at 0.82
and names `metrics.portName` as its subject, with `config-induced-failure` second
at 0.45 *on that same subject*. The two candidates now disagree about which mode
one agreed change is, rather than about what changed.

The sections below are left as written. The delta specs beside this file
describe the deployment staging and are what the main specs receive.

## Context

Every mode Argus handles is a claim about a series. A rule fires on one, the
Investigator retrieves a window, `find_onset` measures the minute the service left
its baseline, and the walk hangs off that minute. FM-26 broke the measurement -
the window is flat and the onset arrives in the alert - and the machinery for that
is built.

A monitoring blind spot breaks something narrower and worse. The series is not
flat; it **stops**, and the shop behind it is perfectly well. Nothing raises,
nothing is slow, no request fails. `GET /metrics` answers 200 with the minutes
before the flag moved and nothing after, every one of them validates,
`MetricsRetrieved` is said with a real count, and every layer between the shop
and the model reports a successful read.

That is the whole difficulty, and it is why the mode belongs to this repo's
current class of defect rather than beside it. The last two sessions closed *a
read Argus could not take was treated as a fact about the service* everywhere a
walk could reach it by failing. Here nothing fails. The absence is
indistinguishable from health at every layer, and the only thing between it and
"we looked, the shop is fine" is prose in an opening message - two paragraphs of
it, both of which currently say something false about a window that stops.

The second half of the difficulty was found by tracing rather than by reasoning:
the mode already walks and already reaches the right verdicts, for the wrong
reason. That is Decision 2 and it is the part that earns spec text.

## Goals / Non-Goals

**Goals:**

- A window whose rows stop is distinguishable from one that was read throughout,
  at every layer a person or a model reads it: the opening message, the
  narration, and the verdict.
- A blind spot's recovery is judged on the evidence the blind spot is about.
- The mode is investigable from channels that already exist, so no recording is
  invalidated.
- Every other scenario's path stays byte-identical.

**Non-Goals:**

- A metrics *source* that refuses. That is an observability outage Argus can see
  and does report, it has a built branch waiting for it, and it is FM-30's
  sibling rather than this.
- The deploy-caused version - a revision that dropped its instrumentation - whose
  answer is a fix rolled forward. FM-26's sibling rule applies: the flag version
  is the one with an action worth taking.
- FM-31 state divergence, the family's last unbuilt member.
- Re-asking the monitoring stack anything. Argus reads the alert it was handed.
- Any new retrieval channel, tool, node, refusal or status, and anything threaded
  between two agents.

## Decisions

### The absence is staged as a window that stops, never as one that is empty

Two stagings were wrong before this one was right, and both errors are worth
keeping written down.

**A refusing `/metrics` is not a blind spot.** An exception is a signal: it
raises, `RetrievalUnanswered` says what could not be read, and
[investigation.py:291](../../../modules/agent_investigator/src/agent_investigator/investigation.py#L291)
ends the walk with the failure named in the incident's own account. That is an
outage Argus sees and reports. The taxonomy's blind spot is the case where the
absence is indistinguishable from health, which a 200 is and a raise is not. The
staging with a branch already waiting for it is the easy half.

**A window with no rows at all is not one either.** `generator.py:1171` builds a
minute for every offset from the span ago up to now, which is the quiet stretch
every other scenario's onset is measured against. A window with nothing in it
would describe a shop that was never instrumented, and an absence rule does not
fire for that - it fires because a series that *was* reporting stopped.

So: rows up to the minute the flag moved, and no row for any minute at or after
it. That is what `absent()` means, and the quiet stretch is what makes the
stopping legible.

It is also a harder case than an empty window rather than an easier one, in the
one way that matters. An empty window is unmistakably nothing. Rows that stop read
as a short window - which is a conclusion the model reaches by itself, unprompted,
and which is wrong.

*Alternative considered:* a refusing source, reusing `_nothing_could_be_read`.
Rejected - it stages a mode Argus already handles, and would reverse a branch
built deliberately for the case it was built for.

*Alternative considered:* an entirely empty window. Rejected as unfaithful to the
alert rule and to how any real metrics source behaves.

### Recovery is the read returning, judged as that

`has_recovered_since` judges a level falling away from an incident's own level
back towards a baseline. Traced against a window that stops, the existing code
reaches the right verdicts by an accident worth naming:

- A wrong candidate leaves nothing at or after the action's minute, so
  [anomaly.py:286-292](../../../modules/argus_core/src/argus_core/anomaly.py#L286-L292)
  answers `False`, the deadline arrives, and
  [trying.py:608-609](../../../modules/agent_mitigation/src/agent_mitigation/trying.py#L608-L609)
  refutes it. The walk moves to the next candidate, as it should.
- The right candidate brings the rows back. The window then has no departure
  anywhere in it, the no-departure clause counts every minute as recovered, and
  the verdict is `CONFIRMED`.

So the confirmation of a blind-spot fix rests on *no series departed* - the exact
inference the opening message is being changed to stop the model making, one
layer down and unguarded. Three consequences, none of them an edge case:

1. A window that returns and is genuinely unhealthy for an unrelated reason
   refutes a fix that worked. The sight came back, which is what the mitigation
   was for, and the rule was asked about levels.
2. Nothing separates telemetry that returned because Argus reverted the flag from
   telemetry that returned on its own.
3. The two cases the whole change exists to distinguish - minutes that are missing
   and minutes that are healthy - are one case to this rule.

The rule is therefore stated for correctness rather than to unblock anything, and
it is honest about being one the existing code already satisfies by luck.

*Alternative considered:* leave it, since the verdicts come out right today.
Rejected on (1) and (2): both are wrong answers reachable without any new fault,
and the second is how a coincidence becomes a confirmed cause in the record.

*Alternative considered:* a new `Verdict` member. Rejected - the verdict is
`CONFIRMED` or `REFUTED` as usual. What changes is what was measured, which is
not a third opinion.

### The distinction is one `has_recovered_since` already draws and discards

Nothing is threaded from the Investigator to the verification, and no mode reaches
`take_action`.

`from_index is None` at
[anomaly.py:291](../../../modules/argus_core/src/argus_core/anomaly.py#L291) is
already the fact wanted: *no minute at or after this one exists*. It returns
`False`, the same answer as *minutes exist and are still at the incident's level*,
and those are two different states - "the sight has not returned" and "the service
has not recovered". Separating them is the whole mechanism.

This is better than every carrier considered, and two of them were considered
seriously:

- **A field on `Reading`.** Rejected, and it would have been a bad bug:
  [reading.py:43-45](../../../modules/argus_core/src/argus_core/models/reading.py#L43-L45)
  is frozen and compared by value precisely so the dispatcher can answer "have I
  read this already" with `in`. A `was_empty` field means a later read that
  returned rows no longer equals the earlier one, so dedup silently stops
  deduping - on the one mode where the same window is genuinely read twice.
- **An `Outcome.measured`-shaped parameter on `TakeAction`.** The right shape for
  a fact that has to travel, and unnecessary here: the verification re-reads the
  same channel every pass, so the fact is in the reading in hand rather than
  inherited from another agent.

A mapping from `MONITORING_BLIND_SPOT` to a recovery rule was never in the
running: it is the table
`unverifiable-action-recommendation` was deliberately written not to be, and
`Action` carries no failure mode anywhere - `mitigating.py` holds
`state.hypothesis` and passes only `hypothesis_id` down. That is the constraint
that keeps the table from being written under deadline, and it is worth keeping.

### Both opening-message paragraphs change in one pass

The onset paragraph and the per-minute paragraph are separately false over a
window that stops, and the per-minute one is worse:

- *"none of them departs from its baseline"* is vacuously true of the rows that
  are there and says nothing about the minutes that are not.
- *"they are the whole span the metrics source keeps - there is no more of this
  channel to ask for"* tells the model not to re-ask the one channel whose return
  is the recovery signal.
- *"An empty cell is a reading this service does not have at all, which is not the
  same as a reading of zero"* arms a distinction about cells at a model facing
  missing rows.

Written together rather than separately, because two paragraphs about the same rows
drift apart if two people write them. FM-26's flat-window wording is left
byte-identical for the window it was written for.

### The mode earns a value though it brings no new action

`RevertFeatureFlag` answers it, exactly as it answers a flag toggle. The precedent
for earning a value anyway is `IN_FLIGHT_COMPATIBILITY_BREAK`, and the test
`failure_mode.py` states is the right one: a mode is a distinction a reader of an
incident makes, never the strategy that answers it.

Here both wrong readings cost something real, which is more than that test asks
for. Read as `feature-flag-toggle`, the incident says the shop misbehaved and
closes with a defect filed against code that has none - and nothing says the
organisation spent that window unable to see anything. Read as the shop being
down, a healthy service is rolled back and people are paged for it.

### The alert comes from the same stand-in that fires every other one

`monitoring.py` in the demo app stands in for a metrics stack with alert rules,
which is a separate party from the shop - so an absence rule firing from there is
coherent rather than a fixture talking about itself. The shop's process is healthy
and serving throughout, so it can still post the webhook. No new component, and
the alert's name is the first in the set whose subject is the monitoring rather
than a symptom.

### No new flag role

The generated scenarios drive off `FEATURE_FLAG`, and the flag world is two flags
in opposite states at boot. A third role would move that world for every scenario,
and the mode needs nothing from it: the existing flag's on-state stops telemetry
publishing, the way it currently selects a failing branch.

### The onset is the first minute with no reading, not the last one with a reading

An absence rule knows the last minute a sample arrived; the incident began in the
minute after it, and that minute is what the alert states. The distinction is one
minute wide and it is worth being exact about, because the other reading makes this
the only scenario whose onset precedes its own cause.

`FlagTimeline.was_on_during` truncates a flip to its minute and treats the whole of
that minute as flagged, so in every flag scenario the first affected minute is the
minute of the flip. Here the first *dark* minute is that same minute. Naming the
onset as the last minute that carried a row would put it one minute to the left of
the cause, uniquely in this set.

This deliberately does not rest on the change channel's default window. That
window ends at the onset, and a seeded flag's audit record is written at the
seeding instant rather than backdated - so in every generated flag scenario the
toggle already falls outside the default and the channel works because the model
asks for a wider one. FM-27 is no different, and an argument from the default would
be an argument that proves too much.

`find_onset` cannot measure that minute, by construction rather than by accident -
the minutes that would carry a departure are the missing ones. So the alert's
`stated_onset` is not a preference, it is the whole of the dating. Written into the
spec explicitly, so that a later change making measurement preferred wherever
possible does not quietly leave this mode undatable.

## Risks / Trade-offs

- **Whether the mode is investigable is unknown until a paid run.** The model gets
  an absence alert, a window whose rows stop, healthy logs across the same
  minutes, and a flag flip at the stated onset. Every piece is retrievable and the
  inference is not obviously hard, but nothing here has ever asked a model to
  conclude *I cannot see*. → Prove the whole walk under the double first with
  hand-authored answers, so the paid run buys only the question of whether the
  model reads it.

- **The recovery change sits on code the last two sessions just landed.**
  `anything_was_read` and the escalate-on-nothing-read branch are load-bearing for
  the control-plane work. → The change is to `has_recovered_since`'s collapsed
  state rather than to that branch, and `anything_was_read` stays True from the
  first poll here, because the pre-onset rows are there to be read.

- **The scenario's own mitigation is verified by the mechanism this change
  rewrites.** Its first recording is therefore also the first evidence for the new
  rule. → The verdict path is deterministic and provable under the double before
  anything is recorded.

- **The minutes must be genuinely missing, not rows of zeros.** A bucket of zeros
  is a flat window, which is FM-26, and the mode evaporates. → Assert absent rows
  directly, as the other scenarios assert their shapes.

- **The opening message is on a path every scenario walks.** → The flat branch is
  left untouched and `e2e_replay` covers all of them for free before anything is
  recorded.

- **The truncated window carries a sharp last minute, which is more evidence than
  an empty one.** It may make the diagnosis easier than the mode deserves. →
  Accepted: it is what the alert rule means, and the compensating difficulty is
  that rows which stop read as a short window rather than as an absence, which is
  the wrong conclusion reached without prompting.
