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
| Change-induced | 31% | Deploy-induced regression (FM-09), config-induced failure (FM-10) | **Partly.** `bad-deployment`, `feature-flag-toggle` and `config-induced-failure` are all here; FM-10 is built, FM-09 is diagnosed but has no mitigation until the git write path |
| Propagation | 28% | Cross-org cascade (FM-01), hidden internal coupling (FM-23) | **Partly.** `upstream-dependency-failure` is FM-01: diagnosed, and escalated because no generic mitigation reaches another company's outage |
| Capacity & resource | 13% | Resource exhaustion (FM-13), autoscaling pathology (FM-25) | **Partly.** `resource-leak` is the leak half of FM-13; demand saturation is not built |
| Foundational integrity | 12% | Silent data corruption (FM-26), control-plane failure (FM-30), monitoring blind spot (FM-27), state divergence (FM-31) | No |
| Recovery/process | 11% | Phased data recovery (FM-21) | No |
| Tail/outlier | 3% | Aggregate-masked tail degradation (FM-06), in-flight compatibility break (FM-35) | No |
| AI-specific | 2% | Output-quality degradation (FM-17), accelerator heterogeneity (FM-33) | No |
| External/adversarial | 1% | External attack (FM-15), supply-chain breach (FM-16) | No, and out of scope |

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

1. **FM-06 Aggregate-masked tail degradation** (3%, but cheap here). The p99
   moves while the average does not. Argus reads p50 and p95 already, and this
   is the scenario that says whether reading them is enough.
2. **FM-23 Hidden internal coupling** (the rest of propagation's 28%). The
   half of that family FM-01 does not cover: the dependency is one of your own
   services, nobody remembered it was on the path, and the correct response is
   neither escalate-and-wait nor revert.

**FM-10 Config-induced failure is built.** `config-induced-failure` stages a
deploy that moves the cache's port in `deploy/values-production.yaml`: every
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
