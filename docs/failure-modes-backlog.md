# Failure modes Argus should eventually handle

What kinds of incident exist, which ones Argus can handle today, and which are
worth building next. Kept so that "add another scenario" is a choice from a list
somebody can argue with, rather than whatever occurs to us on the day.

The categories are not invented here. They come from a published taxonomy built
from 178,000+ status-page incidents and ~1,000 engineering postmortems, which
also supplies the share of real incidents each accounts for - which is the part
that decides what is worth building.

The taxonomy's own distinction is the one that matters to this codebase:

> **Failure mode** is *how* it broke - the pattern. **Root cause** is *why* it
> broke - the technical trigger.

`FailureMode` holds failure modes, because what a mitigation dispatches on is the
pattern. See "A note on the name" below.

## The families, and where Argus stands

| Family | Share | Modes | Argus |
|---|---|---|---|
| Change-induced | 31% | Deploy-induced regression (FM-09), config-induced failure (FM-10) | **Yes.**<ul><li>FM-09 is `bad-deployment`: diagnosed and mitigated by returning the deployment</li><li>FM-10 is `cache-misconfigured`: diagnosed and mitigated by the same rollback, and `feature-flag-toggle` reaches the family by a flag rather than a revision</li></ul>FM-09 and FM-10 share one action: a revision carries the code and the configuration it shipped with, so the platform's rollback answers both |
| Propagation | 28% | Cross-org cascade (FM-01), hidden internal coupling (FM-23) | **Yes.**<ul><li>FM-01 is `upstream-dependency-failure`: diagnosed, and escalated because no generic mitigation reaches another company's outage</li><li>FM-23 is `pricing-service-degraded`: diagnosed and mitigated by restarting a service the alert never named</li></ul>What tells the pair apart is ownership, which the organisation's service register answers and no telemetry does |
| Capacity & resource | 13% | Resource exhaustion (FM-13), autoscaling pathology (FM-25) | **Yes**, and the second family covered entire.<ul><li>FM-13 is built in both halves: `resource-leak` is the leak and `demand-saturation` is the saturation, told apart by whether the consumption moved with the traffic and answered by opposite things - reclaiming what accumulated, or adding capacity the deployment never had</li><li>FM-25 is `autoscaler-flapping`: diagnosed by the one series that moves, and mitigated by raising the controller's floor to its ceiling</li></ul>What tells FM-25 from saturation is whether the capacity is itself moving, because at the bottom of every cycle the rest of the evidence is saturation's exactly |
| Foundational integrity | 12% | Silent data corruption (FM-26), control-plane failure (FM-30), monitoring blind spot (FM-27), state divergence (FM-31) | **Yes**, and the fourth family covered entire.<ul><li>FM-26 is built by both changes that can write wrong data: `silent-data-corruption` is a flag that changes what the shop writes rather than whether it works, and `monthly-totals-falling-behind` is the same drift from a deployed revision - the same symptoms, with a revision in the evidence where the toggle was. Both are found by the shop's own weekly integrity check because no series ever moves. Diagnosed from a flat window and an onset the alert states, and then *not* acted on - the undo - the flag revert or the rollback, whichever the record holds - is named and recommended rather than taken, because only the next run of that check could say whether it worked. The first mode here whose detection is the hard part and the first whose correct outcome is an action Argus declines</li><li>FM-30 is `control-plane-unreachable`, and what is built of it is the response rather than the diagnosis: Argus never investigates the plane and has no mitigation for it, but an action that cannot reach the platform it acts through removes every candidate on that platform at once, so the walk narrows itself to what is still reachable - the flag revert, on a provider that is answering - and escalates naming the platform and the actions it took away where nothing reachable remains. The one mode here whose difficulty is neither detecting the incident nor choosing the action but discovering that most of the actions are gone</li><li>FM-27 is `monitoring-blind-spot`: a deployment that renames the port the shop serves its metrics on, while the shop stays perfectly well, so the window carries a row for every minute up to the one that revision landed in and none at all from there on. Nothing crosses a threshold because for those minutes there is no series to cross one, and the rule that fires is the one every real monitoring stack has and no scenario here had needed - an absence held long enough that it cannot be a scrape that was missed. It states the first silent minute as the onset, because no onset can be measured from the rows that are gone - and the revision landed in that minute, which makes this the one mode whose onset carries no reading of its own: the change sits at it and after the last row there is, so a reader looking for the departure it caused finds an absence instead. What makes it diagnosable is the distance between the last row and the alert's own firing, which Argus states rather than leaves to be inferred, and what corroborates it is a logs channel answering normally across exactly the minutes the metrics do not cover. Mitigated by returning the deployment, where recovery is the readings *returning* rather than a level coming down - and what returning restores is the sight and never the minutes that were missed, which is the one thing it has in common with FM-26. The first mode here whose subject is the monitoring rather than the thing monitored, and the first anywhere whose correct reading of the evidence is *I cannot see*. Its sibling is `monitoring-configuration-drift`: the same silence from a rename that was meant - every port named to one convention in one commit, with the scrape configuration in the repository left behind. No mitigation answers it, because returning the revision would restore the sight by undoing somebody's work, so the walk declines the rollback within reach, proposes the scrape configuration rolled forward, and escalates with the minutes still missing</li><li>FM-31 is `cache-failed-over`: the summary cache's primary dies and a standby that stopped receiving updates three hours earlier is promoted in its place, so the shop serves spend figures the purchase ledger has moved past. The shop is well throughout and every judged series says so, which it shares with FM-26 - what differs is that the copies are wrong and the records behind them are right, so there is something to throw away rather than something to correct. Found by the shop's own reconciliation of the two, which reports how many entries disagree out of how many it checked, the widest gap, and the addresses of the entries themselves. It is the one mode that carries two dates and the only one where taking the wrong one is silent: the promotion is the onset, the oldest purchase the cache never saw dates the replication break three hours before it, and an incident dated from the break begins before anybody could have seen it. Mitigated by discarding the entries the evidence named - the sixth generic mitigation, and the first that removes rather than restores, adds or stops - and confirmed by the count the store returns rather than by watching the service recover, because a window that never departed has nothing in it to recover. The first mode whose action is addressed by something no agent could work out: a key's format belongs to whoever wrote the store, so Argus composes none and carries the ones the check handed over, as a value and never through a prompt. And the first whose fault is not closed by its own mitigation - an entry goes stale the moment its shopper buys again, so the discard clears what was found rather than what is wrong, and the lasting answer is an expiry or a standby nobody promotes while it lags</li></ul>That is a resource leak's shape in a data store, which is where this family touches the capacity one |
| Recovery/process | 11% | Phased data recovery (FM-21) | **No, and out of scope.**<br>The mode is the incident outliving its own fix - a backfill, a queue drained, a consistency check re-run, carrying on for hours or days after the thing that broke has been put right. Argus's bound is a single walk: it reads, it acts within a set of reversible actions, it judges what it did against a window minutes wide, and it hands over what it cannot finish. An incident whose remaining work is somebody else's multi-day restore is one Argus has already escalated, and sitting with it would be waiting rather than responding. So what this family asks for is not a scenario Argus is missing but a different agent's job |
| Tail/outlier | 3% | Aggregate-masked tail degradation (FM-06), in-flight compatibility break (FM-35) | **Yes**, and the third family covered entire.<ul><li>FM-06 is `slow-canary-rollout`: diagnosed and mitigated by putting the flag back</li><li>FM-35 is `half-finished-rollout`: a revision that landed and stopped, diagnosed from whether the rollout converged and mitigated by the rollback that converges the fleet</li></ul>What the two share is a fault that exists for part of the traffic and no more of it - one because a cohort is small, the other because a failing share is the product of two shares |
| AI-specific | 2% | Output-quality degradation (FM-17), accelerator heterogeneity (FM-33) | **Yes**, and covered entire.<ul><li>FM-17 is `categoriser-model-upgraded`: the shop upgrades the model that files every purchase into an aisle, and the new version is served titles in a case it was never trained on, so most purchases land in "General" with no confidence. Nothing fails and nothing slows - filing costs the same whichever model does it - so the error rate, every latency quantile, memory and CPU hold where they were, and the one series that moves is the share of purchases filed confidently, which the shop's own rule watches. What it added is that series: an alert naming its rule brings the series that rule evaluates into the window, judged in the rule's own direction beside the five, so the onset, the verdict on the rollback and the postmortem's figures are all read off the one series that moved. Without it the window is five flat lines under an alarm and the alarm is closed as disproven. Its near-miss is `bad-deployment`, and the evidence the two share is everything but one series: a revision at the onset, a rollback that ends it. What separates them is that requests are not failing or slowing - the output is worse, the service is not. The recorded walk ranked `config-induced-failure` second, which is the other honest reading of a revision whose only change is a value naming the model. Mitigated by returning the deployment and never resolved: the earlier model is serving again, while `main` still names the upgrade and the code that hands it titles it cannot read is unchanged, so a fix is proposed</li><li>FM-33 is `scorer-replica-rescheduled`: one of the fraud scorer's replicas is rescheduled onto an A100, which runs its arithmetic in TF32, and on that replica about half of all purchases are held for review. Nothing was deployed and the change record is empty, so what it added is the placement: read once after the onset, each pod with its card and when it started, and recorded before anything is done. Mitigated by holding the deployment to the one card the pre-onset pods ran on - the seventh generic mitigation, a drain - and never resolved, because the scorer still allows TF32 wherever it runs</li></ul>What tells the pair apart is what changed at the onset: a revision, or a replica placed on another card with nothing deployed |
| External/adversarial | 1% | External attack (FM-15), supply-chain breach (FM-16) | No, and out of scope |

## Scenarios that stage a mode already built

Not every scenario adds coverage. Four stage `feature-flag-toggle`, which the
table already counts, because what they exercise is the walk rather than the
catalogue: `flag-toggle-red-herring` puts a real, logged, irrelevant toggle where
the cause should be, so a mitigation taken on it is refuted and has to be put
back; `competing-flag-changes` moves two flags in one minute and lets the
evidence support both readings; `fallback-disabled` begins the incident by
switching a flag *off*, which an agent that can only switch flags off cannot end;
and `monthly-statement-panel` puts the same fault in the Target Service's largest
module, so that the permanent fix is an answer no unstreamed cap can carry. They
are eval cases, and a green run of one says nothing about which families above
are covered.

## FM-13 Resource exhaustion, split by response

13% of incidents, 2,185 in the sample, and described as one of the most
automatable patterns in the taxonomy - which is why it was built first. It looks
different on the surface every time and is always the same shape underneath: a
finite resource consumed faster than it is replenished.

It splits in two, and the split is by **what the correct response is**, which is
exactly the level `FailureMode` has to name:

- **Demand saturation** - the resource was sized correctly and the load grew.
  Response: scale out, expand capacity, raise a quota.
- **Resource leak / runaway consumption** - growth uncorrelated with traffic.
  Response: **restart, then fix.**

`resource-leak` and `demand-saturation` are the two values, and
`resource-exhaustion` would be too coarse: it maps to two different mitigations,
and a reader who cannot choose between them gets the one that cannot work.

### Scenarios to stage under resource leak

Same failure mode, same mitigation, different resource - so each is a scenario
and none is a new `FailureMode`:

- **Memory leak** - built. Heap climbs, latency follows, OOM and restart.
  Metric: `memory_used_bytes` against `memory_limit_bytes`.
- **Connection-pool exhaustion** - connections checked out and never returned.
  Latency climbs as requests queue for a pool slot, then errors as they time
  out waiting. Metric: pool in-use against pool size.
- **File-descriptor / socket exhaustion** - the same shape, failing at accept
  rather than at query.
- **Disk fill by logs** - the slowest ramp of all, and the one where
  forecasting time-to-exhaustion pays most.
- **Queue runaway** - consumers falling behind producers; depth climbs without
  bound.

### Scenarios to stage under demand saturation

A different mitigation, so a different `FailureMode`:

- **CPU saturation** - built. Traffic grew, the service is correctly sized for
  yesterday. Restarting does nothing; scaling does. Metric: `cpu_used_cores`
  against `cpu_limit_cores`, where capacity is the deployment's total across its
  replicas - so scaling out moves the denominator and the recovery is visible in
  the series the incident was.
- **Traffic spike beyond capacity** - the honest version of the above, where
  the correct response may be to shed load rather than to scale. Not built, and
  a different way of reaching the same mode: shedding load is a mitigation
  somebody has to build and defend.

Worth noting that CPU saturation is the scenario that proves the split is real:
it looks like a leak on a latency graph and a restart makes it briefly better
before it returns, which is the mistake a system without the distinction makes.
That is why the two are staged as a matched pair everywhere they are measured -
the same alert, the same latency climb, the same empty change list, and one
variable.

## What is worth building next

Every family Argus covers is covered entire, and no mode is left that is
neither built nor out of scope.

## Measurements owed, and what each would buy

None of these is a scenario, and each costs real money - a walk is about five
dollars - so they are written down rather than run. What is here is what the spend would
buy, so that a decision to buy it is a decision rather than a habit.

- **The saturation pair's eval bars.** `demand-saturation-is-identified` and
  `resource-leak-is-told-from-demand-saturation` are in the Investigator eval at
  `UNMEASURED`, which is honest and says nothing. Ten runs of each would give a
  rate for the claim the sixth mode rests on: that a reader of the evidence can
  tell load that outgrew its capacity from consumption that climbed on its own.
  One real walk has named it correctly, which is an anecdote rather than a rate.
  Every other bar in that suite is stale for the same reason - the prompt moved -
  so this pool is owed a pass whenever one is bought at all.
- **The capacity pair's eval bars, which are the same pool.** `autoscaler-flapping`
  brings a second pair with the same shape - a moving capacity told from an
  outgrown one - and the two pairs are one purchase rather than two: the same
  alert, the same latency climb, the same empty change channels, and in each case a
  single variable. A rate for either is worth little without the other, because
  what is being measured is not whether one mode is recognised but whether a reader
  separates neighbours that agree on everything else. This pair costs more per run
  than any other in the suite: the near-miss is a whole mitigation attempt - scale
  out, wait the verification timeout, be refuted, undo - so a walk that takes it
  bills for two attempts. What the spend would buy is the only figure that speaks
  to the risk this scenario was built around: how often the evidence is read as
  saturation when the capacity was moving all along, which is the reading that gets
  the mitigation the controller undoes.
- **A rate for Code-Fix answering inside its budget.** There is no eval for
  Code-Fix; `grade_fixes` scores the patches it did produce, and nothing measures
  how often it produces one at all. Two walks have now ended with the agent
  reading to a bound and submitting nothing - and the arithmetic that warns it is
  fixed, which makes this the question worth a rate rather than a fix. What the
  spend would buy: how often a conclusion that names no file leaves the agent
  roaming until a bound binds.
- **What an irreversible action would buy, and what it would cost.** Not a
  measurement but the same kind of entry: a purchase written down so that taking
  it is a decision. `half-finished-rollout` is its motivation, and the sharper
  version of that scenario is the one declined. There, the newer side has already
  written the new shape into something that outlives a rollback, so going back is
  refuted - every replica then reads rows it cannot parse, and the only thing that
  ends the incident is *finishing* the rollout. That version makes the diagnosis
  decide the action, which is stronger than making it decide only the record.

  It was declined on the autonomy rule (§13 of the spec): completing a rollout
  has no undo. There is no returning a fleet to half-deployed, and the revision is
  at every replica the moment it converges - so Argus would diagnose it and ask a
  human, which is FM-01's ending reached at the cost of a sixth action kind, an
  undo descriptor that cannot undo, a gate question about irreversibility and a
  narration for all of it.

  So what a decision here would be deciding is not whether rolling forward is
  correct - it is whether Argus should be able to say *"I know what would fix
  this and I will not do it unasked"* in its own words, as a third refusal beside
  the two the write tier already makes. Today that case is indistinguishable from
  having found no action at all. The distinction is worth writing down and has not
  yet been worth the machinery; the scenario that motivates it now exists, which
  is the part that was missing the last time it was raised.

**FM-06 Aggregate-masked tail degradation is built.** `slow-canary-rollout`
stages the account page's newest figure going out to three percent of traffic,
computed by a walk of the shopper's purchase history once per item. The pages
are correct, so the error rate never moves; ninety-seven requests in a hundred
are untouched, so neither does the median; and three in a hundred is below the
95th percentile by arithmetic, so neither does the tail a monitoring stack
watches. The incident exists in the 99th percentile and nowhere else.

It answers the question the entry used to ask - whether reading p50 and p95 is
enough - with no. So `p99_ms` joined the metric bucket and became the fifth
series the detector judges departure and recovery on, beside the error rate, the
median, the p95 and the heap. Without it the walk never starts, because there is
no onset to start it.

Two things it added beyond the scenario. The on-call provider learned to read
the tail: an incident below the p95 and below the error rate bounded to no
minutes at all, so the provider held nothing and every figure counted from
person-minutes was counted over a night nobody was woken for. And the Target
Service gained its first cohort that is an exact count of a minute's sample
rather than a per-request draw - at three in a hundred of two hundred requests a
binomial draw shows the incident in the p95 or hides it from the p99 about one
minute in twenty-five, and a scenario whose whole claim is that the p95 never
sees this cannot be wrong about it that often.

It is the mirror of the cache misconfiguration, deliberately, and both are built
from the same mixture of a cached path and a recomputed one. That incident hides
*in* the tail, because the tail already described a slow request. This one hides
*behind* it, because it never reaches that far down the distribution. It is also
the one generated scenario that is resolved as well as mitigated: what ends it
is a flag going back, and nothing is left in a heap or a values file for a new
process or a re-sync to bring back.

**FM-10 Config-induced failure is built.** `cache-misconfigured` stages it - the
mode is `config-induced-failure`, and the scenario is one way of reaching it: a
change that moves the cache's port in `deploy/values-production.yaml`. Every
lookup is refused, every page recomputes, and every page is still correct -
the fallback is designed behaviour - so the error rate never moves. The
incident lives entirely in the median, because nine requests in ten used to be
served from cache and the slowest one in twenty always described a recomputed
page. With p50 hidden the detector dates no onset at all, which is the property
the scenario exists for: this is the one incident a monitor watching the tail
never sees.

Three things it added beyond the scenario. The median became a signal the
detector judges departure on, beside the error rate, the tail and the heap.
A third generic mitigation arrived - returning a deployment to the revision it
was running before - and with it the first undo descriptor recording *two*
pieces of prior state, because the platform refuses a rollback while it
reconciles the application itself and suspending that is part of performing the
rollback rather than a separate concern. And the taxonomy stopped reaching the
model as five bare hyphenated names: what each mode means travels with it into
the tool schema, because a name alone underdetermines which mode a deploy at the
onset belongs to.

It is mitigated and never resolved, in the plainest form the system has. The
values file still names the port that broke it, the platform's own
reconciliation is suspended so that nothing re-applies it, and both are what a
withdrawal puts back.

**FM-09 and FM-10 are the pair no telemetry separates, and a fifth retrieval
channel is what separates them.** Both arrive as a deployment before the onset,
both move latency, both are answered by returning the deployment, and every
channel that describes the service describes the two identically. The deployment
history does not help either: an application syncs from one directory for its
whole life, so both scenarios report `deploy` as the path they shipped from, and
a model told to read code-or-configuration off that path reads it off a constant.
What does separate them is inside the commit - one changes
`deploy/values-production.yaml` and nothing else, the other changes
`src/io_shop/spend_summary.py` - so the Investigator reads what a deployment
changed, comparing its revision against the one deployed before it. The fixture
was built for this: `ScenarioDeploy` carries `previous_revision` because "the
entry before this one has to be a real commit whose diff against this one is the
diagnosis".

**FM-09 Deploy-induced regression is built.** `bad-deployment` stages the other
half of the pair: a revision that derives a shopper's lifetime average from the
purchases once per purchase - the same figure, quadratic cost, on the path every
request takes. The shop runs without a summary cache, so every request pays and
the median, the 95th and the 99th all climb by the same multiple. Nothing fails,
so the error rate never stirs, and no log line mentions a release - the deploy
exists in the Argo CD history alone, which is what makes the change channel
load-bearing rather than corroborating.

It answers with the same action FM-10 does, and that is the finding rather than
a compromise. A revision carries the code and the configuration it shipped with,
so the platform's rollback is one operation over both, and a second action kind
performing the identical call would be machinery bought for nothing. What
separates the two modes is the account the incident gives and the fix left
afterwards - a values file for one, the service's source for the other - which
is why a mode is a distinction a reader of an incident makes rather than one the
strategy lookup makes for them.

**FM-01 Cross-org cascade is built.** `upstream-dependency-failure` stages a
payment provider that stops answering: errors and latency move together, memory
is flat, nothing changed, and the mode maps to no generic mitigation - so the
incident is named exactly and handed to a person. What it added beyond the
scenario was the distinction at the gate between a cause nothing answers and an
action nobody could identify.

**FM-23 Hidden internal coupling is built.** `pricing-service-degraded` stages
the other half of propagation: the account page asks a service the same company
runs for the basket total, and that service becomes an order of magnitude slower
to answer. It answers every call, so nothing fails and the error rate never
moves; the shop simply waits, and the median, the 95th and the 99th all climb
together. That shape says *deployment*, and the deploy history is empty - so the
reading the metrics suggest is refuted by the one channel that could confirm it,
and the only evidence naming a cause is a WARN line in the shop's own log saying
which host the time went to.

What it added is the distinction the family turns on, and it is not a signal.
Whether the thing on the other end can be restarted or only telephoned exists in
no metric and in no log: it is recorded by a person in a service register, which
Argus reads as evidence rather than holding as configuration. A restart is
therefore admitted by two questions rather than one - its kind is pre-authorised,
and its address is a dependency the register marks as the organisation's own -
and the second refuses in its own words, because "Argus does not do that" and
"Argus does not touch that" ask different people for different things.

It is also the first mode whose permanent fix is out of Code-Fix's reach. The
shop's source is correct; what is wrong is in a service whose repository Argus
was never pointed at, and a timeout or a fallback on the calling side is a
design decision rather than a defect to patch.

**FM-13's other half is built.** `cpu-saturation` stages demand saturation: the
shop's reported volume ramps to several times its baseline and holds, CPU pins
against a ceiling it cannot exceed, every quantile climbs together, and the heap,
the error rate and every change channel stay exactly where they were. Nothing
is wrong with the service. It is too small.

Three things it added beyond the scenario, and the first is the one that matters
most. **A fourth generic mitigation, and the first that adds something rather
than restoring something.** Every mitigation before it put something back - a
flag to the state it was in, a process to a fresh start, a deployment to the
revision before it - and scaling out returns to nothing. That is not a weakening
of what admits an action unasked: the criterion is membership of the declared set,
never whether the change can be put back, and this is the member that makes that
legible. Google SRE's own list of generic mitigations names adding capacity beside
draining, rolling back and restarting.

**The first bound on how far one mitigation may go.** The gate's cap bounds how
many times a repeatable mitigation may be attempted within an incident; the write
tier's ceiling bounds how large any one attempt may make the deployment. Either
alone leaves the other's failure available - a cap of two with no ceiling permits
an unbounded second attempt, and a ceiling with no cap permits attempts without
end below it. The ceiling is the tier's rather than the strategy's, for the reason
the mapping from a service to a workload is: it is a fact about the estate.

**A signal that is retrieved and not judged.** The pair on the bucket is
`cpu_used_cores` against `cpu_limit_cores`, and the detector goes on dating an
onset from five series without it. Utilisation tracks traffic, so judging it would
move the anchor back to the minute the load arrived - minutes before anything was
wrong, and sometimes a busy stretch in which nothing ever was. The incident is the
latency the saturation caused, which the five already see.

It is mitigated and never resolved. The repository still asks for the size that
was too small, reconciliation is suspended so nothing re-applies it, and the load
that outgrew the capacity is still arriving - so a withdrawal returns the shop to
saturation, which is the honest ending. Capacity is also the one shortfall no
patch closes, and what that costs is worth writing down rather than assuming:
the walk asks the code tier like any other mode, and the agent answers from the
repository in front of it. Measured against the fixture, it proposes a patch -
correctly, because the shop's main branch carries a real fault for other
scenarios to stage, and a reader sent looking without a file named finds it. So
what the record holds for this mode is a mitigation that ended the incident and
a proposal that is beside the point, and the incident is `mitigated` either way.
The claim that a capacity shortfall gets no patch is a claim about a model's
reading rather than about Argus, and nothing here asserts it.

**FM-25 is built on it.** Nothing could stage an autoscaler misbehaving until a
replica count existed, was visible in telemetry, and could be changed; demand
saturation is what made all three true.

**FM-25 Autoscaling pathology is built.** `autoscaler-flapping` stages the same
surge and one difference: the deployment has a controller whose scale-down
stabilisation window is zero. Readiness lag makes the cycle three minutes - it
scales up on a saturated minute, the minute after is still served at the old size
while the replicas warm, and the third runs at the ceiling and reports a fraction
of its CPU target, which the controller answers by taking the replicas straight
back. So `cpu_limit_cores` takes two values across one window, and that is the
whole diagnosis: nothing is wrong with the code, the configuration, the flags or
the heap, and at the bottom of every cycle the telemetry *is* saturation's.

Three things it added beyond the scenario.

**The first mode whose fault is a control loop.** Every mode before it is a change,
a state or a resource - something was shipped, something was switched, something
filled up. A controller goes on deciding, which is why the answer is aimed at what
it is *allowed* to do rather than at what it has done.

**A fifth generic mitigation, and the first that stops something.** The three
before scaling out put something back and the fourth added something; this one
takes away a controller's room to shrink, by raising the floor it may fall to
until it meets the ceiling somebody already declared for the deployment. The
criterion is unchanged again, and that is the point of saying so twice: what
admits an action unasked is membership of the declared set, never the kind of
change it makes.

**The first demonstration that a mitigation under a live controller has a timer on
it.** Setting the replica count directly works for about a minute and is then
re-derived away, because the controller owns that number - so the near-miss here is
not a worse answer but a correct-looking one that expires. That is also what makes
the scenario refutable: the wrong action is undone by the estate rather than by a
rule in Argus.

It is mitigated and never resolved. The values file still declares the window that
flaps, so putting the floor back returns the shop to flapping - and a walk that
answered this with a restart would have changed nothing at all.

**FM-35 In-flight compatibility break is built, and tail/outlier is the third
family covered entire.** `half-finished-rollout` stages a revision that changed
the shape of what the summary cache stores, deployed and then paused half-way
through its rolling update. Three replicas write the new shape and three were
deployed before it existed, so an account page fails when a replica on the older
side draws an entry a replica on the newer side wrote. The error rate steps, no
quantile moves at all, the cache answers at the ratio it always did, nothing
accumulates and nothing saturates.

Three things it added beyond the scenario.

**The first mode with no culprit commit.** Every mode before it has something a
reader can point at - a commit, a value, a flag, a heap, a controller, somebody
else's service. Here both revisions leave `tests/io_shop` green, which makes "no
revision is at fault" a fact about the fixture rather than a claim in a
description: `grade_fixes` has nothing to grade, because there is no failing test
for a patch to turn green. What is left to fix is the expand step of an
expand-contract migration nobody performed - a version that could read both
shapes, deployed before the one that writes only the new one - and that is a
process rather than a patch.

**The first channel that reads a deployment as a stretch rather than an
instant.** The five before it all read a deployment as an event: the history
records that a sync happened, the diff records what that sync carried, and
metrics, logs and the flag provider describe the service. A rollout is a stretch,
and a stretch that has not ended is invisible to every one of them - so the sixth
channel reads the live Deployment and reports which revision the platform is
converging on, how many replicas have reached it, how many have not, whether the
rolling update is paused, and when it entered that state. No new source: the
application, the credential and the route are the deploy history's own.

**A failing share that is the product of two shares.** It is the share of entries
written by the newer side times the share of reads taken by the older one, scaled
by how much of the traffic the cache answers at all - so it is zero before a
rollout begins, zero once it converges, and largest in the middle. About one
request in five here, with the cache carrying its usual nine in ten. No other
mode in the set produces a rate that a rollout *finishing* would take to zero,
and it is arithmetic a reader can check against the replica counts the platform
reports.

**The near-miss is refuted in the record rather than by the estate, which is
uncomfortable and is the mode's whole point.** A reader who calls this a bad
deployment reaches the right action - the rollback - so the incident ends either
way, and nothing in the walk would have caught the mistake. What the wrong
reading costs is the account: a postmortem naming a revision that is not at
fault, an action item filed against code with no defect in it, and nothing said
about the rollout that was left half-done, which is the only thing that will
happen again. Every other near-miss in this file is refuted by the fixture, where
a wrong mitigation changes nothing and the telemetry says so. This one is carried
by an eval case instead - `bad-deployment` must not be determined where the
deploy landed and did not finish - because the e2e case cannot assert that a
wrong reading would have failed, when it would not have.

It is mitigated and never resolved, and for a reason the other two rollback modes
do not share. There the revision carried the fault and going back removes it;
here going back removes nothing and *converges* the fleet, and one version
reading and writing one shape is a shop that works whichever version it is. The
repository still declares the revision that was going out, reconciliation stays
suspended so nothing re-applies it, and a withdrawal returns the shop to a
rollout stopped half-way.

**FM-31 State divergence is built, and foundational integrity is the fourth
family covered entire.** `cache-failed-over` stages the summary cache losing its
primary and a standby being promoted in its place - one that stopped receiving
updates three hours earlier, so from the promotion onwards the shop serves spend
figures the purchase ledger has already moved past. Nothing fails. The error
rate, every quantile, the heap, the CPU and the replica count are flat across the
whole window, the cache answers at the ratio it always did, and the pages that
read it render perfectly well and wrongly. What pages is the shop's own
reconciliation of the two: for each account it compares what the cache holds
against the purchases behind it, and reports how many disagree out of how many it
checked, the widest gap in cents, the item discrepancy, and the address of every
entry that differs.

It is the one mode that carries two dates, and the only one where taking the
wrong one is silent. The onset is the promotion; the oldest purchase the cache
never saw dates the replication break three hours before it. Both are true, both
are in the payload, and an incident dated from the break begins hours before
anything was there to be seen - which no later reader can detect, because the
earlier date is the more precise-looking of the two.

Four things it added beyond the scenario.

**A sixth generic mitigation, and the first that removes rather than restores,
adds or stops.** The criterion is unchanged and saying so a third time is the
point: what admits an action unasked is membership of the declared set, never
the kind of change it makes. This is the member most likely to be mistaken for a
weakening, because throwing data away sounds heavier than putting a value back
and is not - what is discarded was derived from records the action never
touches, the service recomputes on the next read, and what is gone cannot be
stale. It is also the first action that reaches a datastore directly rather than
a control plane, which is a third platform the walk can find unreachable.

**The first confirmation that does not come from the window.** Every mitigation
before it is judged by watching the service: the action is taken, the window is
re-read, and a level coming back down is the verdict. Here nothing ever departed,
so there is nothing to come back - and a rule that reads a flat window as
recovery would confirm every action ever taken on a well service. So an action
whose own answer states what it changed is confirmed from that answer instead,
and the count the store returns is the whole of the evidence. What makes this
safe rather than a loophole is a sibling question asked first - whether the
window holds a departure to have recovered *from* - because "it never got worse"
and "it got better" are the same sentence to anything that only measures levels.

**The first action addressed by something no agent could have worked out.** The
other five are addressed to a flag the provider recorded or a service the alert
named. An entry in a store is addressed by a key, a key's format belongs to
whoever wrote the store, and a constant in Argus would be this system holding
another service's internals with nothing downstream able to tell a derived key
from a real one. So the check that found the divergence hands its keys over and
Argus composes none. They ride the record as a value and never reach a prompt:
the model is told how many entries disagree and by how much, which is what it
reasons about, and hundreds of addresses re-rendered on every round of a ReAct
loop would be the incident's largest cost and none of it evidence.

**The first fault its own mitigation does not close.** The stale set grows - an
account diverges the moment its shopper buys again - so the key list is a
snapshot at the minute the check ran, and the discard clears what was found
rather than what is wrong. That is a resource leak's shape in a data store, which
is where this family touches the capacity one, and it is why the lasting answer
is an expiry on the entries or a standby nobody promotes while it lags, neither
of which is a mitigation.

**The near-miss is another mode in the same family.** A reader who calls this
silent data corruption has the symptoms right - a well service, a flat window, an
integrity check that pages - and reaches an action that repairs nothing: the
records are correct and there is no write to put back. What separates them is
which side is wrong, and the evidence says so plainly in the reconciliation's own
figures. It is carried by an eval case rather than by the fixture, because a walk
that reached for a flag revert here would be refused by the gate for a reason
that says nothing about the misreading.

It is mitigated and never resolved. The promoted standby is still the primary,
still lagging, and still the thing the deployment points at, so the entries the
discard cleared come back wrong as soon as they are recomputed from a cache
nobody has fixed. A withdrawal puts nothing back either, and says so rather than
staying silent: a discard owes no undo, because writing the stale figures back
would be recreating the incident - which is a different fact from an undo that
was attempted and failed, and the one a reader of a withdrawn incident would
otherwise have to infer from an absence.

**FM-31's undated sibling is built.** `cache-failed-over-undated` stages the same
failover with nobody recording when it happened, so the shop's check can say what
is wrong and not since when: its alert carries the finding and no onset. Nothing in
the window contradicts a claim no series carries, so the alarm is not disproven,
and nothing departed, so there is no onset to measure either. The walk is anchored
on the minute the alarm fired - where to look from, not when the incident began -
and ends where the dated walk does, with the stale entries discarded.

**FM-27's deliberate sibling is built.** `monitoring-configuration-drift` stages
the blind spot's silence from a change that was meant: a revision names every
port in the deployment for the protocol it carries and says so in a comment,
while `deploy/scrape.yaml` still selects the metrics port by its old name. The
alert, the window, the logs and the onset are the blind spot's exactly; only the
diff differs, so the pair measures one variable - a rule applied, or one value
changed.

It is the first mode whose correct ending is a proposal with the sight still
lost. No mitigation answers it, and a mode nothing answers ends the mitigation
phase rather than passing to the next explanation, which here is reliably the
rollback that would undo the convention. Code-Fix proposes the scrape
configuration rolled forward with a test that reads both files, the incident
escalates holding that proposal, and the postmortem says the service was still
unobserved when it closed rather than reporting the window before the onset as
the incident.

**FM-17 Output-quality degradation is built.** `categoriser-model-upgraded`
stages a deployment that moves the shop's purchase categoriser from one model to
the next. The upgrade is served titles in a case it was never trained on, so most
purchases are filed under "General" with no confidence, while every request is as
quick and as successful as before. The shop's rule pages on the share filed
confidently falling, and that share is the only series in the window that moves.

What it added is the rule's own series. An alert naming its rule brings the series
that rule evaluates into the window, judged in the rule's direction beside the
five, and every reading of the incident is taken off it: the onset, the verdict on
the rollback and the postmortem's figures. Without it the window is five flat
lines under an alarm, and the alarm is closed as disproven.

Its near-miss is `bad-deployment`, which shares everything but one series - a
revision at the onset, a rollback that ends it. Requests failing or slowing is
that mode; the output getting worse while the service does not is this one. The
recorded walk ranked `config-induced-failure` second, the other honest reading of
a revision whose only change is the value naming the model.

It is mitigated and never resolved. The rollback loads the earlier model again,
while `main` still names the upgrade and the code that hands it titles it cannot
read is unchanged, so a fix is proposed.

**FM-33 Accelerator heterogeneity is built, and AI-specific is covered
entire.** `scorer-replica-rescheduled` stages the shop's fraud scorer on
three replicas that have always run on V100 nodes, until the scheduler replaces
one and the replacement lands on the cluster's one A100. The A100 runs the
scorer's arithmetic in TF32, which the scorer allows, and its two largest weights
cancel only in full precision - so on that replica about half of all purchases
are held for review. Nothing was deployed, nothing fails and nothing slows. The
share held for review rises from about one in twenty to nearly one in five, and
the shop's rule on it pages.

What moved is where a replica runs, and nothing in the change record holds it: a
reschedule is not a deploy. What it added is that reading. The Investigator reads
the placement once after the onset - each pod, its node, the card that node
carries and when the pod started - marks the pods that started at the onset, and
publishes it to the timeline before anything is done. It added the seventh
generic mitigation too, a drain: the deployment is held to the one card the
pre-onset pods ran on, worked out from that recorded placement and never from a
read made when acting.

Its near-miss is FM-17, which shares every series: the rule's own departs and
the other five are flat. A revision at the onset is that mode, and a replica
moved to another card with nothing deployed is this one. The recorded walk ranked
output-quality degradation second, for a reason it could not name - the honest
reading of the same window with the placement set aside.

It is mitigated and never resolved. Every replica is back on V100, while the
scorer still allows TF32 wherever it runs, so the next reschedule brings it back.
The recorded fix folds the cancelling weights into one coefficient, so the score
no longer depends on the card.

## Why they are called modes

`FailureMode` was `CauseType` until the taxonomy above made the mismatch
plain. The two values it held were never causes: `bad-deployment` and
`feature-flag-toggle` are patterns - *something changed and broke it* - where
a cause is a technical trigger, *the divisor was zero for shoppers who bought
nothing this month*.

The pattern is the right thing to dispatch on, because a mitigation answers the
pattern: restarting is the answer to a leak whatever leaked, and rolling back
is the answer to a bad deploy whatever the bad code did. So the design was
right and only the word was wrong.

## Sources

- [SRE failure mode taxonomy](https://stackgen.com/blog/sre-failure-mode-taxonomy)
- [Resource exhaustion as a failure mode](https://stackgen.com/blog/sre-resource-exhaustion-failure-mode)
- [The root causes behind 178,000 incidents](https://stackgen.com/blog/sre-root-cause-taxonomy-online-services)
