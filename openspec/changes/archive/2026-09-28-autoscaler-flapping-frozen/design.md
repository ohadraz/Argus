## Context

Every failure mode Argus holds is something that happened once. A flag was
moved, a revision shipped, a value changed, a heap filled, load arrived - and
each is answered by doing one thing once. The record afterwards reads as a
sequence because the world it describes is one.

FM-25 is the first mode whose fault is a **control loop**, and that changes two
things Argus has never had to handle. The incident has no onset in the sense the
others do - it has a period. And a mitigation taken against it is contested:
something is still running that will undo what Argus does. The scale-out spec
already reasons about exactly this for Argo CD's reconciliation ("a mitigation
with a timer on it") and cannot demonstrate it, because until now nothing in the
fixture ever put a replica count back.

What makes it buildable now is the previous change. `cpu_limit_cores` reports the
capacity a minute was served at, `Capacity` records replica counts as a history
of moments rather than a value, and Argo CD's `scale` action is wired through the
platform stand-in. A controller that moves the count is a new producer of
resizes, not a new mechanism.

## Goals / Non-Goals

**Goals:**

- A scenario whose signature is a capacity that is itself moving, with nothing
  deployed, no flag touched, memory flat and nobody having scaled anything.
- A fifth generic mitigation that stops the oscillation, and stops it through the
  controller rather than around it.
- Two refutable wrong answers: a restart, which changes nothing, and a
  **scale-out**, which the autoscaler puts back - the near-miss punished by the
  fixture rather than by a rule.
- Mitigated, never resolved, with a withdrawal that returns the shop to flapping.

**Non-Goals:**

- Scaling in, or reducing capacity by any route. Being wrong about adding
  capacity costs money and being wrong about removing it costs an outage, and
  that judgement is unchanged by this mode.
- Deleting the autoscaler. A pin is reversible in one field; a deletion is a
  resource somebody has to recreate from a manifest, and Argus does not remove
  things it cannot put back in the same call.
- Diagnosing *why* the autoscaler flaps. The mode says the control loop is the
  fault; which field is wrong is a fix, and the fix is a patch to a values file
  like any other.
- Requiring Code-Fix to propose that patch. The stabilisation window is genuinely
  in git and genuinely patchable, which is a difference from demand saturation
  worth having - but asserting the agent finds it would be a requirement on a
  model's reading, which is the lesson the last change paid for.

## Decisions

### The pathology is flapping, and it is demand saturation plus a controller

The scenario reuses the surge exactly - the same `_SURGE_PEAK_MULTIPLE` of 4.5
and the same ten-minute ramp - and adds an autoscaler. That is not economy; it is
the strongest possible framing of the distinction. At the bottom of every cycle
the telemetry *is* demand saturation's telemetry, so the near-miss diagnosis is
genuinely tempting rather than straw. What separates them is one series moving:
capacity.

It also inherits sizing that is already justified. 4.5× baseline over three
replicas puts demand about nine tenths of a core past what the shop has, and a
doubling clears it with room to spare. So three replicas is insufficient and six
is comfortable, which is the pair a flap needs.

Alternatives considered and rejected in the proposal's own framing: scaling on
the wrong signal overlaps `internal-dependency-failure` and needs the
dependency's latency to be a function of the shop's replica count; scaling into
an exhausted connection pool is answered by scaling *in*, which Argus may not do.

### The flap's period comes from readiness lag, not from a short window

The misconfiguration in git is `behavior.scaleDown.stabilizationWindowSeconds: 0`
- the field whose default of 300 seconds exists to prevent exactly this, and the
real reason real autoscalers thrash. But a zero window alone would flap at the
controller's sync period, four times a minute, and a per-minute bucket reporting
the last observed capacity would then be a coin toss rather than a signature.

What produces a minute-scale cycle is the lag every autoscaler actually fights:
new replicas take about a minute to become ready and start serving. So the cycle
is three minutes.

| Minute | Replicas ready | Utilisation | What the controller does |
|---|---|---|---|
| 0 | 3 | pinned at capacity | scales to 6 |
| 1 | 3 (six exist, warming) | pinned at capacity | holds - still high |
| 2 | 6 | about 0.56 | scales to 3 |
| 0 | 3 | pinned at capacity | scales to 6 |

`cpu_limit_cores` reports the capacity the minute was *served* at, so it reads
3, 3, 6, 3, 3, 6 - which is the diagnosis.

**The period of three is load-bearing arithmetic, not flavour.** With
`anomaly_persistence_minutes` at 2, an onset needs two consecutive departed
minutes and recovery needs a stretch with a clear minute in it and no run of two
elevated ones. This cycle gives elevated minutes in runs of two and clear minutes
alone, which is the only shape that satisfies both: the incident is detected, and
no down-swing can be read as an action having worked. A symmetric two-minute
period would confirm any action at all on the next good minute, which would make
the wrong answer accidentally right - the property the whole capacity pair exists
to avoid.

The alternative was a queue that drains across minute boundaries, so that no
minute ever falls clear. It works and it needs a decay constant tuned against the
detector's hysteresis bar to land between two thresholds. Readiness lag needs no
constant, is a truer account of why autoscalers flap, and leaves the generator's
latency a function of one minute's own pressure as it is today.

### Pinning is a patch of the autoscaler, because the deployment's count is not Argus's to set

Argo CD's `scale` action writes `spec.replicas` on the Deployment. A live
autoscaler owns that field and re-derives it from its own metric within a sync
period, so a `scale` here is a write that is undone - which is precisely the
incident. The mitigation has to address the controller.

The operation is `minReplicas` raised to the autoscaler's own `maxReplicas`. One
field, and it both halts the oscillation and leaves the deployment at the largest
count somebody already declared for it. The autoscaler stays in place and keeps
working; it simply has no room to scale down. Verified against Kubernetes' own
documented behaviour: equal bounds fix the count and effectively disable
autoscaling.

Rejected: deleting the HPA (a resource to recreate, and a second write to set the
count); patching `behavior.scaleDown.stabilizationWindowSeconds` back to 300
(that is the *fix*, it asserts what the right window is, and it leaves the shop
oscillating for as long as the controller takes to notice); setting
`maxReplicas` down to `minReplicas` (pins the shop at three, saturated).

**Pinned at the ceiling and not at the count in force.** The oscillation means
the count in force is a coin toss: caught at the bottom of the cycle, pinning it
would freeze the shop saturated and then judge a mitigation against it. The
ceiling is also the only number available that Argus is not inventing - a bound a
human declared for this deployment, read from the live resource, exactly as
scale-out reads the count it doubles. It is still clamped by
`THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR`, which is what keeps an autoscaler declared
with `maxReplicas: 400` from being obeyed.

### The wire shape, verified against Argo CD's own swagger

`POST /api/v1/applications/{name}/resource` is `ApplicationService_PatchResource`.
It takes `resourceName`, `namespace`, `group`, `version`, `kind` and `patchType`
as query parameters, and **the patch as a JSON-encoded string in the body** - not
as an object. The same path answers `GET` as `ApplicationService_GetResource`,
which is how the autoscaler's current bounds are read, addressed by
`group=autoscaling, version=v2, kind=HorizontalPodAutoscaler`.

So the tier learns one endpoint, one patch type
(`application/merge-patch+json`, the default) and one resource kind. The stand-in
gains a `POST` handler on a path it already answers `GET` on, and learns to
answer that `GET` for a second kind.

`patchType` travels URL-encoded, which is a documented trap on this endpoint
rather than a detail: an unencoded `application/merge-patch+json` is what the
vendor's own issue tracker has people filing bugs about.

### Suspending reconciliation is the general rule, not a GitOps rule

Argo CD re-applies the HPA manifest from git at its next sync, so the pin needs
automated sync suspended for the reason the scale-out did. What this change makes
plain is that the rule was never about git: **anything that re-derives the state
a mitigation just set has to be suspended before it is set**, and a GitOps
controller and an autoscaler are two such things. The scale-out requirement gets
that generalisation as a delta.

`AutoscalerUndo` therefore records two things, as `ReplicaUndo` does - the floor
the autoscaler had, and whether the platform was reconciling the application
itself - and the sync setting is never restored to a default, because Argus does
not turn on a thing it did not turn off.

### The autoscaler is declared in git and live only when staged

`deploy/values-production.yaml` gains an `autoscaling` stanza with the zero
window, so the fault is in the repository, is readable at HEAD by
`read_repository_file`, and is patchable. The **live** autoscaler is scenario
state: the platform stand-in reports an HPA resource, and `Capacity` simulates
the controller, only while this scenario is staged.

That is the liberty every scenario in the fixture already takes - the shop's
`main` always carries the monthly-spend fault and only the flag scenario stages
it - so a latent misconfiguration in git that nothing is currently running is
consistent with how this fixture works. Declaring a live autoscaler for every
scenario would be the alternative, and it would scale the demand-saturation shop
out on its own and destroy that scenario's grading.

### Each minute's count is computed, not recorded

`Capacity` today answers `replicas_during` from a list of resizes, oldest first.
A controller cannot be expressed that way: its resizes are not events anybody
performed, and recording them as they are observed would make a window read
differently the second time it is fetched - which is the one property the whole
generator rests on.

So for this scenario the count for a minute is **derived** from the minute's
position in the cycle, with the cycle anchored on the ramp, and the derivation
stops the moment a pin is in force. Deterministic, replayable, and a window
fetched twice reads the same both times. Argus's own resizes stay what they are
today - moments in a list - and a pin is a third thing: a floor, from an instant
onwards, that the derivation is bounded below by.

## Risks / Trade-offs

**The cycle's arithmetic is tuned against a detector constant.** Period three
works because `anomaly_persistence_minutes` is 2. A deployment that changed the
setting would break the scenario's detection or its grading, silently. →
Asserted, not assumed: the demo app's tests pin the shape of the cycle, and the
e2e suite asserts an onset is found and that a restart is refuted. The dependency
is stated in the scenario spec so that a reader of either one finds it.

**A near-miss diagnosis costs a whole mitigation attempt.** A walk that says
demand saturation scales out, waits the verification timeout, is refuted, undoes
it, and only then tries again - which is minutes of wall clock and a second round
of tokens. → That is the correct behaviour and the point of the scenario, but it
makes this the longest walk in the suite and the most expensive to record. The
cap on repeatable mitigations bounds it.

**Scale-out's undo runs against a moving count.** A refuted scale-out restores
`was_replicas` - the count it read before acting - and the autoscaler has since
moved the live count away from it. The restore therefore writes a number that is
immediately re-derived. → Honest and harmless: the undo's job is to leave nothing
Argus set behind, and it does. Worth stating in the scale-out delta rather than
discovering in a recording.

**Two verbs in the estate now write a replica count.** A reader of the record
sees a scale-out and a pin and has to know which owns the count. → The narration
says what each did in the words of what it changed - a count, or a floor - and
`the_subject_of` gives both the application.

**`maxReplicas` is a number the fixture chooses and the ceiling is a number
Argus holds.** With `maxReplicas: 6` and a ceiling of 12, the clamp never fires
in the demo, so the bound is untested by any scenario. → Covered by the write
tier's own unit tests, which is where the scale-out's ceiling is covered too; a
scenario built to exercise a bound would be a scenario about Argus rather than
about an incident.

**Thirteen recordings go stale.** The seventh mode's meaning changes the
Investigator's tool schema, so every `both-*` corpus is re-recorded. → Known
cost, and the same cost the sixth mode carried. Nothing is recorded until the
free gates and a rehearsal pass, per the `preflight-before-paid-runs` skill.
