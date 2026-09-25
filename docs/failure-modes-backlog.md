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
| Change-induced | 31% | Deploy-induced regression (FM-09), config-induced failure (FM-10) | **Partly.** `bad-deployment`, `feature-flag-toggle` and `config-induced-failure` are all here; FM-10 is built, FM-09 is diagnosed and dispatches to no strategy - the only mode of the five that does not |
| Propagation | 28% | Cross-org cascade (FM-01), hidden internal coupling (FM-23) | **Partly.** `upstream-dependency-failure` is FM-01: diagnosed, and escalated because no generic mitigation reaches another company's outage |
| Capacity & resource | 13% | Resource exhaustion (FM-13), autoscaling pathology (FM-25) | **Partly.** `resource-leak` is the leak half of FM-13; demand saturation is not built |
| Foundational integrity | 12% | Silent data corruption (FM-26), control-plane failure (FM-30), monitoring blind spot (FM-27), state divergence (FM-31) | No |
| Recovery/process | 11% | Phased data recovery (FM-21) | No |
| Tail/outlier | 3% | Aggregate-masked tail degradation (FM-06), in-flight compatibility break (FM-35) | **Partly.** `slow-canary-rollout` is FM-06: diagnosed and mitigated by putting the flag back. In-flight compatibility is not built |
| AI-specific | 2% | Output-quality degradation (FM-17), accelerator heterogeneity (FM-33) | No |
| External/adversarial | 1% | External attack (FM-15), supply-chain breach (FM-16) | No, and out of scope |

A mode's mitigation is a separate question from its coverage, and FM-09 is where
the two come apart: `bad-deployment` is diagnosed and named, and it is the one
mode of the five that reaches no strategy. What it waits for is a strategy, not a
mechanism - returning a deployment to a revision it already ran is what the
config rollback does, through the same platform sync, and a code deploy is the
same action against a different revision.

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

`resource-leak` is the value, and `resource-exhaustion` would be too coarse:
it maps to two different mitigations.

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

A different mitigation, so a different `FailureMode` when it is built:

- **CPU saturation** - traffic grew, the service is correctly sized for
  yesterday. Restarting does nothing; scaling does.
- **Traffic spike beyond capacity** - the honest version of the above, where
  the correct response may be to shed load rather than to scale.

Worth noting that CPU saturation is the scenario that proves the split is real:
it looks like a leak on a latency graph and a restart makes it briefly better
before it returns, which is the mistake a system without the distinction makes.

## What is worth building next

In order of share, minus what is out of scope for a demo:

1. **FM-23 Hidden internal coupling** (the rest of propagation's 28%). The
   half of that family FM-01 does not cover: the dependency is one of your own
   services, nobody remembered it was on the path, and the correct response is
   neither escalate-and-wait nor revert.
2. **FM-35 In-flight compatibility break** (the other half of tail/outlier's
   3%). A deploy that is correct on both sides of itself and wrong for the
   requests that span it.

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
A third generic mitigation arrived - returning a deployment to a configuration
revision it already ran - and with it the first undo descriptor recording *two*
pieces of prior state, because the platform refuses a rollback while it
reconciles the application itself and suspending that is part of performing the
rollback rather than a separate concern. And the taxonomy stopped reaching the
model as five bare hyphenated names: what each mode means now travels with it
into the tool schema, because a model shown only the names reads a deploy that
landed at the onset as a bad deployment, which is defensible and is not what
dispatches to the right mitigation.

It is mitigated and never resolved, in the plainest form the system has. The
values file still names the port that broke it, the platform's own
reconciliation is suspended so that nothing re-applies it, and both are what a
withdrawal puts back.

**FM-01 Cross-org cascade is built.** `upstream-dependency-failure` stages a
payment provider that stops answering: errors and latency move together, memory
is flat, nothing changed, and the mode maps to no generic mitigation - so the
incident is named exactly and handed to a person. What it added beyond the
scenario was the distinction at the gate between a cause nothing answers and an
action nobody could identify.

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
