## Context

Three generated scenarios exist, and each stages its condition as something the
shop's own code really consults: a flag's state, a heap that really accumulates,
a payment provider that really refuses. The generator holds one dataclass per
condition (`FlagTimeline`, `ProviderOutage`), draws from it only when the
scenario stages it, and computes every minute from the condition as it stands
when the minute is asked for. That is what makes an incident recoverable rather
than replayed, and it is the mechanism this scenario joins.

What the Target Service impersonates is as important as what it runs. It is one
FastAPI process. Unleash is real; GitHub is real; the deployment platform,
Stripe, BambooHR and PagerDuty are routes on that same process returning
vendor-shaped JSON. The restart mitigation already goes out through the
platform's own resource-action endpoint - Argus believes it is talking to Argo
CD, and the process resets its own state. This change adds a second platform
operation on exactly that footing.

The one thing that is genuinely real here is the configuration. `repository_source`
already reads the Target Service's repository from GitHub at a commit and diffs
two commits, and the Code-Fix path already writes branches and pull requests
against it. Putting the values file in that repository means the port change is
a commit that exists, not a sentence the fixture asserts.

## Goals / Non-Goals

**Goals:**
- A scenario whose only moving signal is latency, with the error rate flat -
  the shape no existing scenario has.
- A third generic mitigation, reversible, that is neither a toggle nor a
  restart, and whose undo restores two things.
- Diagnosis from a real diff: the platform names a revision, the repository
  answers what that revision changed.
- Detection that is principled rather than lucky - the median is what moves
  most here, so the median becomes a signal.

**Non-Goals:**
- No Kubernetes, no Argo CD installation, no Redis container, no new
  repository. The cache is a callable seam; the platform is the stand-in that
  already exists.
- Not demand saturation, and not a cache that is merely cold. The cache is
  healthy and unreachable, which is what makes this a config fault.
- Not a runtime configuration service. A cache endpoint is deployment
  configuration, and modelling it as a runtime tunable would be the wrong layer
  and a surface nobody has.
- Argus does not write the configuration repository as part of mitigating. The
  fix is a pull request on the ordinary Code-Fix path, reviewed by a human.

## Decisions

**The cache is a callable seam, not a server.** `LookUpSummary` beside
`AskTheProvider`, for the reason that one is a callable: the generator renders
200 pages a minute across a 90-minute window, and a socket per render is tens of
thousands of connections per `/metrics` read. What is real is the shape of the
answer and what the shop does with it. *Alternative:* a real Redis in
compose - rejected, because it buys a realistic connection failure at the cost
of a container, a dependency and a per-render round trip, and the failure it
buys is one the seam reproduces exactly.

**Latency is composed per request, not added as a constant.** Each rendered page
draws a hit or a miss and takes that path's time, so `p50` and `p95` fall out of
the sample the way they do in a real percentile. This is how the median-moves-
further-than-the-tail property arises at all: assert it as a multiplier on each
quantile and the scenario is merely a claim about percentiles, where composed it
is a consequence of them. *Alternative:* an additive wait, as the provider
outage uses - right there, because a timeout is a wait the whole request sits
through; wrong here, because the fault changes which path a request takes.

**The condition is drawn only when staged.** `CacheEndpoint` is consulted only
for a scenario that stages one, exactly as `ProviderOutage` is, because each
minute seeds one `Random` and a draw inserted into the sequence shifts every
draw after it. This is what keeps every existing scenario's figures
bit-identical, and it is the constraint that decides where the new draw goes.

**The values file lives in the Target Service's own repository.** A
`deploy/values-production.yaml` holding the cache endpoint, changed by a real
commit. *Alternative:* a separate `io-shop/k8s-configs` repository, which is
what the authored `bad-deployment` scenario's `repo_url` already names - and
which points at nothing today. Creating it would be more faithful to how a large
shop separates config from code, and costs a second repository to create,
index, authenticate against and keep in step. The single repository is already
real, already read, already indexed; the diff Argus needs is the same diff
either way.

**The mitigation is the platform's rollback, not a commit.** Argo CD's rollback
re-syncs an application to an entry in its own deployment history without
touching git. That is what makes it admissible as a generic mitigation: it
replays a revision that was already reviewed and already ran, where writing to
the configuration repository would be Argus authoring an infrastructure change,
which §13 forbids without approval. *Alternative:* a revert commit plus a sync -
rejected on exactly that ground.

**Automated sync is suspended first, and the undo restores both.** A real Argo CD
refuses a rollback while automated sync is enabled, and re-syncs to the bad
revision the moment it is re-enabled. This is a vendor constraint rather than a
design choice, and it is worth having: it makes the rollback visibly a
mitigation rather than a fix, and it produces the first undo descriptor carrying
two pieces of prior state. An application already not auto-syncing is left not
auto-syncing - the undo restores what was there, never a default.

**The tail does not catch this incident, and that is the point.** With a hit
ratio around 90% and a tight miss distribution, `p95` already describes a miss
before the onset and describes the same miss after it - it barely moves. `p50`
goes from the cached path to the recomputed one, a twenty-fold step. So the
aggregate the system watches most confidently is the one that misses this, and
the median is the only thing that sees it. That is the aggregate-masking shape
the backlog lists as FM-06, arrived at from the config family.

This requires the median to be readable, and today it is not. The generator
gives `p50` and `p95` the same *absolute* wobble - ±8ms on a 45ms baseline
against ±8ms on 215ms - which makes the median ±18% and the tail ±4%. That is
backwards: in a real service the tail is the jittery one. Measured consequence:
adding `p50` to the detector under the current noise model moves both flag
scenarios' onsets from 12:10 to 12:09, dating each a minute before its own flag
was turned on.

So the wobble becomes proportional, and then `p50` joins the detector. *Alternative:*
raise the hit ratio above 95% so both quantiles sit on the cached path and the
tail catches it too - which works, needs no detector change and no re-recording,
and throws away the only scenario in the set where the aggregate lies. Rejected
for that reason.

**`cache_hit_ratio` is a ratio, and absent where there is no cache.** A ratio
because, unlike memory against a limit, there is no crossing to forecast.
Absent rather than zero where a service consults no cache, because zero is what
a cache answering nothing reports, and a reader must be able to tell a service
without a cache from a service whose cache is gone - the same distinction
`memory_limit_bytes` already makes by being absent.

## Risks / Trade-offs

- **Detection rests entirely on the median** → By construction the tail does
  not catch this. If `p50` is ever dropped from the detector, or the noise model
  regresses to equal absolute wobble, this scenario silently becomes
  undetectable rather than merely mis-dated. Both the spec and the detector say
  why the median is read.
- **Proportional wobble changes every scenario's figures** → `p95`'s spread
  moves too, and each scenario's departure threshold is derived from its own
  window's spread. The onset check in task 1.3 covers every existing scenario,
  not only the two that regressed. The committed e2e recordings are *not*
  affected: the double serves a recording by name, not by matching the prompt,
  so changed figures cannot invalidate one.
- **Two mitigations now target the same service** → A restart is admissible and
  will be proposed for a latency departure by any hypothesis reading it as
  resource pressure. It will not help, which is correct and is the lesson the
  red-herring scenario already teaches, but it costs a mitigation round.
- **The values file must be read by the service, not just present** → A file
  nobody reads is a fixture pretending to be configuration, and the first person
  to change the port and see nothing happen will find that out. The service
  reads the endpoint from it at startup.
- **A second real commit in the demo repository affects the code index** → The
  index reconciles against a commit; adding a file changes what is indexed.
  Confirm the reconciler handles a YAML file it has no reason to embed, and that
  the seeded commit for other scenarios is unaffected.
- **Rollback semantics are vendor-specific** → The auto-sync constraint is Argo
  CD's. The write tier's adapter is where that knowledge belongs, as the restart
  adapter already holds the resource-action shape, so nothing above the tier
  learns which platform answered.

## Migration Plan

No migration. Every change is additive: a new failure mode value, a new action
type, a new optional metric field, a new scenario, and a new route on the
stand-in. Existing scenarios' telemetry is unchanged by construction, and the
one behavioural change to existing paths - `p50` joining the detector - is
verified against the existing e2e set before it lands.

## Open Questions

- Should the rollback be offered for `BAD_DEPLOYMENT` too? The operation is the
  same and the mode is absent from the strategies map today. Out of scope here,
  but the strategy being registered for one mode and not the other is a line
  somebody should defend rather than inherit.
