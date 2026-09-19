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
| Change-induced | 31% | Deploy-induced regression (FM-09), config-induced failure (FM-10) | **Partly.** `bad-deployment` and `feature-flag-toggle` are both here |
| Propagation | 28% | Cross-org cascade (FM-01), hidden internal coupling (FM-23) | No. The spec's "upstream dependency failure" scenario is FM-01, and correct behaviour is escalate |
| Capacity & resource | 13% | Resource exhaustion (FM-13), autoscaling pathology (FM-25) | **Next.** See below |
| Foundational integrity | 12% | Silent data corruption (FM-26), control-plane failure (FM-30), monitoring blind spot (FM-27), state divergence (FM-31) | No |
| Recovery/process | 11% | Phased data recovery (FM-21) | No |
| Tail/outlier | 3% | Aggregate-masked tail degradation (FM-06), in-flight compatibility break (FM-35) | No |
| AI-specific | 2% | Output-quality degradation (FM-17), accelerator heterogeneity (FM-33) | No |
| External/adversarial | 1% | External attack (FM-15), supply-chain breach (FM-16) | No, and out of scope |

## FM-13 Resource exhaustion, split by response

13% of incidents, 2,185 in the sample, and described as one of the most
automatable patterns in the taxonomy - which is why it is next. It looks
different on the surface every time and is always the same shape underneath: a
finite resource consumed faster than it is replenished.

It splits in two, and the split is by **what the correct response is**, which is
exactly the level `FailureMode` has to name:

- **Demand saturation** - the resource was sized correctly and the load grew.
  Response: scale out, expand capacity, raise a quota.
- **Resource leak / runaway consumption** - growth uncorrelated with traffic.
  Response: **restart, then fix.**

`resource-leak` is the value being added. `resource-exhaustion` would be too
coarse, because it maps to two different mitigations.

### Scenarios to stage under resource leak

Same failure mode, same mitigation, different resource - so each is a scenario
and none is a new `FailureMode`:

- **Memory leak** - the one being built. Heap climbs, latency follows, OOM and
  restart. Metric: `memory_used_bytes` against `memory_limit_bytes`.
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

## What is worth building after resource leak

In order of share, minus what is out of scope for a demo:

1. **FM-10 Config-induced failure** (part of the 31%). Closest to what exists -
   a non-code change breaking the service - and the flag scenario is already
   a narrow case of it.
2. **FM-06 Aggregate-masked tail degradation** (3%, but cheap here). The p99
   moves while the average does not. Argus reads p50 and p95 already, and this
   is the scenario that says whether reading them is enough.
3. **FM-01 Cross-org cascade** (28%, the second-largest family). Already in the
   spec as "upstream dependency failure", where correct behaviour is to
   recognise it is not fixable and escalate. Argus has the escalation path; what
   is missing is the evidence that distinguishes an upstream failure from an
   internal one.

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
