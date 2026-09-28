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
| Change-induced | 31% | Deploy-induced regression (FM-09), config-induced failure (FM-10) | **Yes.** `bad-deployment`, `feature-flag-toggle` and `config-induced-failure` are all here, all diagnosed and all mitigated. FM-09 and FM-10 share one action: a revision carries the code and the configuration it shipped with, so the platform's rollback answers both |
| Propagation | 28% | Cross-org cascade (FM-01), hidden internal coupling (FM-23) | **Yes.** `upstream-dependency-failure` is FM-01: diagnosed, and escalated because no generic mitigation reaches another company's outage. `pricing-service-degraded` is FM-23: diagnosed and mitigated by restarting a service the alert never named. What tells the pair apart is ownership, which the organisation's service register answers and no telemetry does |
| Capacity & resource | 13% | Resource exhaustion (FM-13), autoscaling pathology (FM-25) | **Yes**, and the second family covered entire. FM-13 is built in both halves: `resource-leak` is the leak and `demand-saturation` is the saturation, told apart by whether the consumption moved with the traffic and answered by opposite things - reclaiming what accumulated, or adding capacity the deployment never had. FM-25 is `autoscaler-flapping`: diagnosed by the one series that moves, and mitigated by raising the controller's floor to its ceiling. What tells it from saturation is whether the capacity is itself moving, because at the bottom of every cycle the rest of the evidence is saturation's exactly |
| Foundational integrity | 12% | Silent data corruption (FM-26), control-plane failure (FM-30), monitoring blind spot (FM-27), state divergence (FM-31) | No |
| Recovery/process | 11% | Phased data recovery (FM-21) | No |
| Tail/outlier | 3% | Aggregate-masked tail degradation (FM-06), in-flight compatibility break (FM-35) | **Partly.** `slow-canary-rollout` is FM-06: diagnosed and mitigated by putting the flag back. In-flight compatibility is not built |
| AI-specific | 2% | Output-quality degradation (FM-17), accelerator heterogeneity (FM-33) | No |
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

In order of share, minus what is out of scope for a demo:

1. **FM-35 In-flight compatibility break** (the other half of tail/outlier's
   3%). A deploy that is correct on both sides of itself and wrong for the
   requests that span it. It is first by elimination rather than by share: with
   capacity covered entire, it is the only remaining half of a family that has a
   built half - and a family half-covered is where the distinctions are cheapest
   to draw, because the neighbour it has to be told apart from already exists.

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
