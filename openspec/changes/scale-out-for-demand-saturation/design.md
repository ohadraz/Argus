## Context

Argus owns three generic mitigations and every one of them puts something back:
a flag to the state it was in, a process to a fresh start, a deployment to the
revision before it. Demand saturation is answered by none of them, because the
correct response is to *add* something - capacity the deployment never had.

The evidence is the other half of the gap. A leak and a saturated service are the
same shape on a latency graph, and the fixture has no series that separates them:
`request_volume` is on the bucket but describes the load rather than the
service's headroom, and nothing reports headroom at all. So a model handed this
incident today has `resource-leak` as the nearest name on the list, and the
mitigation that follows makes the shop briefly better before it returns - the
exact mistake the taxonomy says a system without the distinction makes.

Three things are already in place and shape everything below. The deployment is
Argo CD-managed, and the demo app stands in for it at
`POST /argocd/{application}/resource/actions/v2` - the endpoint the restart
already goes through. `deploy/values-production.yaml` already carries
`replicas: 3`. And the rollback has already established what it costs to change
live state under a GitOps controller: suspend the application's own
reconciliation first, and record two pieces of prior state rather than one.

## Goals / Non-Goals

**Goals:**

- A signal that tells consumption tracking traffic from consumption that does
  not, retrievable through the channel the Investigator already has.
- A mode whose meaning states what separates it from its three nearest
  neighbours, since a mode is only worth adding if a reader of the evidence can
  choose it.
- A fourth generic mitigation that adds capacity, is reversible, and is
  pre-authorised on the same ground as the other three.
- A scenario where the wrong answer is refuted rather than accidentally right.
- The replica count becomes a thing that exists, is visible, and can be changed -
  which is the floor FM-25 stands on.

**Non-Goals:**

- Autoscaling, in either direction. Nothing here reacts on its own, and FM-25 is
  a change of its own.
- Scaling *in*. Argus never reduces capacity: the blast radius of being wrong is
  an outage, where the blast radius of being wrong about scaling out is a bill.
- Load shedding, rate limiting, or a quota. Those are the other answer to a
  traffic spike and each is a mitigation somebody has to build and defend.
- A code fix. The shop's source is correct.
- Changing `replicas` in the repository. That is a pull request against somebody
  else's deployment configuration, which is the tier Argus does not act in
  unasked.

## Decisions

### CPU is carried as used-against-capacity, and capacity is the deployment's total

`cpu_used_cores` and `cpu_limit_cores`, floats in cores, mirroring
`memory_used_bytes` / `memory_limit_bytes` exactly: the ratio is derivable from
the pair and the pair is not derivable from the ratio. Capacity is the
deployment's total across its replicas rather than one replica's limit, which is
the choice that makes the pair say what this mode needs it to say - scaling out
moves the denominator, so the recovery is visible in the same series the incident
was, with no second field reporting a replica count.

`cpu_used_cores` is required and `cpu_limit_cores` is nullable, for the reasons
already written for the tail and the memory limit: every process uses CPU, so an
absence would be a measurement that went astray, and a deployment imposing no
limit is ordinary, where zero would be indistinguishable from no capacity at all.

*Alternative considered:* a `cpu_utilisation` ratio. Rejected on the pair's own
argument - and it would have hidden the thing the mitigation changes.

*Alternative considered:* a `replicas` field on the bucket. Rejected: a replica
count is platform state rather than telemetry, and the capacity total already
carries what a reader needs. It is also the field FM-25 will want, and it should
arrive with the change that has a use for it.

### Usage clamps at capacity; the slowdown comes from demand, which does not

A heap cannot exceed its limit, so the leak's pressure ratio is bounded by one.
Demand can exceed capacity and routinely does, which is the whole of this
incident - so two quantities are needed where the leak needed one. `cpu_used_cores`
is the *served* figure and clamps at `cpu_limit_cores`, because a service cannot
use more CPU than it has; the latency multiple is computed from demand over
capacity, which keeps climbing after the gauge has stopped. A gauge pinned at the
ceiling while latency goes on rising is therefore the signature, rather than a
number growing without bound - which is also what a real utilisation graph looks
like.

### CPU is retrieved and not judged

The detector goes on dating an onset from five series - the error rate, the
median, the 95th, the 99th and the heap - and CPU is not a sixth. It fires
nothing, so this is not a question about false alerts: it dates the onset inside
a window somebody already retrieved, and the date is what every window after it is
anchored on. Utilisation tracks traffic, so judging it moves that anchor back to
the minute the load arrived - which is minutes before anything was wrong, and
sometimes a busy stretch in which nothing ever was. The incident is the latency
the saturation caused, which the existing five already see, and the minute they
date is the minute customers were hurt.

It joins `request_volume` and `cache_hit_ratio`, which are on the bucket and
unjudged for the same reason. Stated as a requirement rather than left as an
omission, because the memory precedent reads as an argument for judging every
gauge.

### The action names the application and the tier resolves the count

`ScaleOut(application=...)` carries no number, following `RollBackDeployment`
rather than `RevertFeatureFlag`. A target count is meaningless without the count
it replaces; the count it replaces is live state that only the write tier can
read; and a strategy asserting "six" would be asserting the deployment is at
three - a fact no evidence in front of it carries, and one that is wrong the
moment anybody has scaled anything. So the tier reads the running count, doubles
it, and bounds the result by a ceiling it is configured with, answering with both
figures - exactly as the rollback reads the history and reports which entry it
returned to.

The ceiling is the tier's and not the strategy's for the same reason the
restart's mapping from a service to a workload is: it is a fact about the estate,
and the tier is where facts about the estate live. It is also the second of two
bounds, and they answer different questions - the gate's cap bounds how many
times a repeatable mitigation may be attempted, and the ceiling bounds how far
one attempt may go.

*Alternative considered:* a factor on the action (`ScaleOut(by=2)`). Rejected as
a parameter nothing would ever vary, carried across four module boundaries.

### Argo CD's own `scale` action, through the endpoint the restart already uses

Argo CD ships a built-in `scale` resource action for `apps/Deployment`
(`resource_customizations/apps/Deployment/actions/scale`) which reads a
`replicas` parameter and sets `spec.replicas`. It runs through
`POST /api/v1/applications/{app}/resource/actions/v2`, which is the endpoint
`restart` already goes through and which the demo app already stands in for. So
the write tier learns one more action name and one parameter, and does not learn
a second platform: patching Kubernetes' `scale` subresource directly would be
the alternative, and it would put a Kubernetes client in a tier that has so far
needed only Argo CD.

The parameter is a *string* on the wire, per the action's own tests. That is the
vendor's wire vocabulary, so the tool takes an `int` and the adapter spells it.

### Suspending reconciliation is part of performing the scale

Argo CD reverts a live `spec.replicas` at its next sync, back to the `replicas: 3`
that git holds - so a scale-out under automated sync is a mitigation with a
timer on it, and the shop would return to saturation at a moment nothing in the
record explains. The tier therefore suspends automated sync first, exactly as the
rollback does, and for exactly the same reason.

Which makes the undo descriptor two-part: `ReplicaUndo` carries `was_replicas`
and `was_syncing_itself`. `was_syncing_itself` is the setting as it was found and
never a default - an application somebody had already stopped reconciling must be
left stopped. The descriptor is built by the tier, not at proposal time, because
both figures are read from the platform.

### The replica count is a history, not a value

The fixture generates a finished minute once and remembers it, keyed on every
value that minute is computed from. A scalar replica count in that key would
therefore regenerate the *already-served* minutes at the new size the moment
anybody scaled: the saturated stretch would report the capacity it has now, the
climbed latency would be gone with it, and the incident would disappear from the
window exactly when the mitigation wants to be judged against it.

So capacity is a history of resizes, and a minute asks it which count was serving
*then* - the same shape `ProcessLifetime` has for the process's restarts, and for
the same reason. Putting a count back is one more entry rather than an erasure,
because the minutes the shop spent large are also what happened. This is the
fixture's own version of the rule the rollback already follows: a mitigation ends
a stretch rather than clearing it.

### The scenario's live condition is the replica count, and the surge is a ramp

Generated, not authored. Seeding sets a surge whose reported volume ramps from
the baseline to several times it over the first minutes and then holds; CPU
demand is computed from that volume against the live replica count, which the
`argocd` stand-in's `scale` action changes. So the telemetry reacts to whatever
anybody does:

- scaling out drops utilisation below the pressure threshold, latency returns to
  baseline, and the mitigation is **confirmed** on the detector's own recovery
  rule;
- restarting the shop moves the process start time and changes nothing else -
  demand and capacity are both where they were - so it is **refuted**, which is
  what makes the split worth having rather than a distinction nobody could be
  wrong about;
- reverting a flag changes nothing, because no flag is staged.

The error rate stays at baseline throughout. A saturated service does eventually
time out, but errors are the leak's late signal and borrowing them here would
blur the one pair of scenarios this change exists to separate. Memory stays flat,
nothing is deployed, and no flag moves - so the evidence is: every quantile up
together, volume up with it, CPU pinned at capacity, and every change channel
empty.

### The mode is `demand-saturation`; the scenario is `cpu-saturation`

The mode is named for the response, because that is what a mode dispatches on -
and `resource-exhaustion` would be too coarse for the reason already written on
`RESOURCE_LEAK`. The scenario is named for the resource, because a scenario is
one way of reaching a mode and the next one under it (a traffic spike answered by
shedding load rather than scaling) is a different way. It is the same relation
`cache-misconfigured` has to `config-induced-failure`.

### Mitigated, never resolved

Git still says three replicas, reconciliation is suspended so nothing re-applies
it, and the traffic is still elevated. A withdrawal puts the count and the sync
policy back, which returns the shop to saturation - the honest outcome, and the
same shape the cache misconfiguration has.

There is no code fix, so this is the second mode out of Code-Fix's reach after
`internal-dependency-failure`. Nothing new is needed for that: the walk already
has an answer for a mode with no patch to propose.

## Risks / Trade-offs

**Two new fields on `MetricBucket` re-date every recorded walk.** The bucket
reaches the model as text in a metrics summary, and the mode list reaches it in a
tool schema - so all twelve `both-*` corpora become answers to a prompt that no
longer runs. → They replay by queue order, so nothing breaks; they become stale
evidence. The last such change re-recorded them for about $29. The eval bars are
already owed a paid run (nine cases x ten), so the sequencing is one paid
checkpoint at the end covering the new corpus, the twelve, and the evals -
not a re-record per step.

**A restart is refuted, and refutation costs a walk its cheapest mitigation.**
If the Investigator reaches for `resource-leak` here, the walk restarts the shop,
measures no improvement, and moves on - which is correct behaviour and a longer
incident. → That is the scenario's purpose, and the eval case asserting the mode
is what measures how often it happens.

**Doubling is a blunt policy.** Load at 4.5x capacity is not answered by 2x, and
the walk would have to scale twice. → The gate's cap already permits a bounded
number of attempts of a repeatable mitigation, and the ceiling stops the second
one from being unbounded. The fixture's surge is sized so that one doubling
clears it, so the two-attempt path is possible rather than required.

**Capacity as a deployment total is a fiction one replica's metrics would not
support.** A real scrape reports per-pod CPU, and the total is a sum somebody
computes. → It is the sum a monitoring stack shows for a service, which is the
level every other field on this bucket is already at: the error rate and the
quantiles are the service's, not one pod's.

**`cpu_used_cores` clamping at capacity means the gauge understates demand.** A
reader cannot tell 1.1x capacity from 3x from the gauge alone. → That is true of
every real utilisation graph, and it is what the latency and the volume beside it
are for. The scenario's description says what the load actually was.

## Open Questions

- The ceiling's value, and whether it is configuration or a constant in the tier.
  A constant is honest for a fixture with one deployment; configuration is what a
  second deployment would want.
- Whether the surge's shape should also be reachable from the console, or only by
  id like `monthly-statement-panel`. It is an audience question, not a
  capability one.
