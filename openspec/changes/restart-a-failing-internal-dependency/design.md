## Context

Two things are true of every mitigation Argus has taken so far, and FM-23 is
the first incident that breaks both.

The subject comes from the alert. `RestartServiceStrategy` and
`RollBackDeploymentStrategy` both take `service` handed down from the incident
and say so at length in their docstrings: not from Argus's configuration, which
would hardcode one deployment's answer, and not from the hypothesis, whose
`subject` is the model's description of what went wrong rather than an address.
Those arguments are right and stay right. What they assume is that the service
that was paged is the service at fault.

And the environment has one service. `restart_resource_name` is configured once
as `io-shop`; `ObserveStartTime` is a no-argument protocol reading the shop's
own `/metrics`; the demo app *is* the platform stand-in and stands in for one
application. Nothing here can express an action addressed to a second service,
let alone confirm that it landed.

FM-01 is built and is the near neighbour: the shop's own log lines name the
payment provider's host and the status it answered with, and the mode maps to
no strategy, so the incident is named and handed over. FM-23 has the same shape
of evidence and the opposite outcome, and what separates them is a fact neither
the telemetry nor the logs carry: who owns the thing being blamed.

## Goals / Non-Goals

**Goals:**

- An incident where the alerting service is well, diagnosed as a named
  dependency's fault, mitigated by restarting that dependency, and verified by
  the alerting service's own recovery.
- A defensible bound on what Argus may touch, derived from evidence rather than
  from configuration.
- The propagation family closed: FM-01 and FM-23 distinguished by the one thing
  that actually distinguishes them.

**Non-Goals:**

- Per-service metrics and logs. The read tier goes on serving one service's
  telemetry - see the decision below, where this is the point rather than a
  saving.
- A fourth action kind. A restart is a restart; only its address is new.
- Resolving the incident. The fault is in another service's code, in a
  repository Argus does not index and Code-Fix cannot open. This is the first
  scenario whose permanent fix is out of reach by design.
- Any change to how a *kind* is admitted. `GENERIC_MITIGATIONS` stays a set of
  three kinds, read in one sitting.

## Decisions

### The dependency is diagnosed from the caller's side, never from its own telemetry

Argus reads `io-shop`'s metrics, `io-shop`'s logs, and a catalogue. It never
reads `io-pricing`'s metrics, because `io-pricing` does not have any here.

This is the decision the whole change rests on, and it is a claim about the
failure mode rather than a shortcut. The coupling is *hidden*: the reason
nobody knew the dependency was on the path is exactly the reason nobody put a
dashboard on it. An Argus that diagnosed this by pulling up the dependency's own
error rate would be staging an incident where the coupling was never hidden at
all - and it would answer the question by assuming away the thing that makes it
hard.

So the evidence is what a client genuinely has: its own request timings, its own
log lines attributing time to an outbound call, and a catalogue saying what that
call goes to.

*Alternative considered and rejected:* giving `get_metrics_summary` and
`get_log_lines` a `service` parameter and having the demo app serve telemetry per
service. It is the larger change by a wide margin - the detector, the postmortem's
evidence sources and every consumer of a metric window would follow - and it buys
a scenario that is easier, not truer.

### The catalogue is evidence, not configuration

A new read tool answers, for a service, what it calls: each dependency's name,
what it is for, and whether the organisation owns it. It reaches the Investigator
typed, like every other channel, and it reaches Mitigation as a value handed to
`propose_action` alongside `flag_changes` - fetched by the Orchestrator before
the choice is made, so choosing an action still cannot depend on a provider being
reachable and the gate can still be passed before any I/O happens on Argus's
behalf.

Putting it in Argus's own settings was the obvious alternative and is wrong twice
over. It would hardcode one deployment's topology into the agent, which is the
objection the restart strategy already makes about its own subject. And it would
be unreadable by the Investigator, so the model could not use ownership to tell
FM-23 from FM-01 - which is the single discrimination this scenario exists to
test.

The payment provider gets a catalogue entry too, marked as somebody else's. FM-01
then stops being diagnosed by an assumption and starts being diagnosed by a
lookup, without a single one of its requirements changing.

### The hypothesis carries an address, and it is not `subject`

A new field, `faulting_service`, beside `subject` rather than inside it.

`subject` is documented as the specific thing the cause *names* - a flag, a
description - and the restart strategy refuses to treat it as an address for a
reason it states with an example: "kuki heap (memory_used_bytes / heap of
2048MiB limit)" is a real thing a model wrote there, and a platform call sent to
it asks about a resource nobody has. Overloading it now would make that
docstring false and would make every existing strategy's refusal to read it
arbitrary.

So `faulting_service` is separate, it is optional, and it is populated only for
a mode that needs one. Determining `internal-dependency-failure` without one is
not a diagnosis anything can act on, and the answer tool's schema says so.

*Consequence:* the model can write any string there. That is what the next
decision is for.

### The blast radius is a second gate, and it is about the instance

`is_a_generic_mitigation` is a question about the kind, never about the
instance, and its docstring is right that absence from the set is a refusal
rather than a default. That stays exactly as it is.

What is added beside it is a second question, and it is the one the kind cannot
answer: may Argus touch *this* service? The answer is yes when the catalogue
lists it as a dependency of the alerting service and marks it as ours, and when
it is the alerting service itself. Everything else is refused - a third party's
name, a service in another part of the estate, and prose the model mistook for
a hostname.

Two gates rather than one widened gate, because they fail for different reasons
and a reader picking the incident up needs to know which: "Argus does not do
that" and "Argus does not touch that" are different sentences.

*Alternative considered:* have the strategy propose `None` when the address is
not an owned dependency. Rejected - `None` already means "there was a strategy
and it found nothing to act on", and folding a refusal into it would publish a
gap in the investigation where there was a bound on authority.

### The restart's resource and its confirmation both come from the service

Two configuration values assume one application: `restart_resource_name`, which
names what the platform restarts, and `the_process_start_time`, which reads the
shop's `/metrics` to confirm a new process is serving.

The resource name is derived from the service being restarted. The confirmation
moves to the platform's own view of what is running - Argo CD's
`GET /api/v1/applications/{name}/resource-tree`, whose `nodes[].createdAt` is a
pod's creation timestamp - so that a restart of `io-pricing` is confirmed by
looking at `io-pricing` rather than by watching the shop's buckets and concluding
from an unmoving number.

No liberty is taken in the shape. This is the route a real platform answers the
question on, and a pod's creation time is what a real operator reads to see
whether a restart landed; the stand-in reports one pod per application and the
fields a caller confirming a restart actually reads.

One mechanism for both services, not two. The shop's restart changes its
confirmation source and nothing else: the tree reports the same instant the
metric bucket carries, because both read the same field of the same state. That
the shop's start time is now visible in two places is not duplication to be
removed - a monitoring stack reports a process start time because it reports
series, and a platform reports a pod's creation time because it reports pods, and
both exist in every real deployment.

*Granularity, checked:* Kubernetes timestamps are second-resolution, so a pod's
`createdAt` is too. It is enough here because the value a restart is judged
against is the *previous* process's start time, which is minutes old - two
restarts inside one second is the only case it could not separate, and nothing
performs one.

### `internal-dependency-failure` is a mode, on the reader's test

The test a mode has to pass is whether a reader of an incident distinguishes it,
which is the rule FM-09 settled when two modes came to share one action. A
reader distinguishes this one from `resource-leak` sharply: the postmortem says
the shop was well and the pricing service was not, and the fix afterwards is in
another team's repository. That two modes now both answer with a restart is the
ordinary shape of a lookup, exactly as two modes answering with a rollback is.

*Alternative considered:* no new mode - call it `resource-leak` and let the
address do the work. Rejected. It would have the incident report say the shop
was leaking when the shop was fine, and it would leave the escalate-or-act
decision with nothing to hang on: `upstream-dependency-failure` maps to no
strategy precisely because the mode says whose the failure is.

### The scenario is a second service the shop forgot it calls

`pricing-service-degraded`. The account page asks `io-pricing` what a shopper's
basket would cost with their current discounts, through a seam the generator can
answer without a network round trip - the same seam the payment provider uses,
for the same reason.

The degradation is slowness, not failure: pricing answers everything, slowly.
The shop's error rate never moves, memory is flat, no flag moved and nothing was
deployed, while the median and both tails climb together.

That signature is deliberately *not* FM-01's, which is errors and latency
moving together. It is, on the surface, `bad-deployment`'s - and the deploy
history is empty, so the reading a model reaches for first is unsupported and it
has to look further. What resolves it is the shop's own log lines, which
attribute the time to the outbound call, and the catalogue, which says the thing
being called is ours.

*Alternative considered:* give it FM-01's exact signature, so that ownership is
the *only* discriminator. It is the sharper eval and the worse scenario: the two
cases would then differ in nothing a reader of the telemetry could name, and a
model that got it right would be indistinguishable from one that guessed. The
discrimination this stages is honest and still hard.

*What ends it:* restarting `io-pricing`. Restarting `io-shop` - the obvious
wrong move, and the one every existing strategy would make - changes nothing, so
the hypothesis is refuted and the walk goes on. That is a property worth a
requirement, because it is the only thing that proves the address is load-bearing
rather than decorative.

## Risks / Trade-offs

- **The model reads it as a bad deployment** → the deploy history is empty for
  the window and the change channel reports nothing; if an eval shows the
  confusion surviving that, the fix is the evidence the Investigator is shown -
  the attributed log lines - and not the scenario.
- **The model reads it as FM-01 and escalates** → this is the case the scenario
  exists for, and the catalogue is the answer to it. If the model escalates with
  the catalogue in hand, that is a finding about the tool's wording, which is
  cheap to change and is where the effort belongs.
- **A restart is confirmed differently after this change** → the shop's
  confirmation source moves from `/metrics` to the platform's application view;
  the leak scenario's e2e case is the regression test, and it is free under
  replay.
- **The address is a free-text field a model fills in** → two gates stand behind
  it, and the catalogue-bound one refuses anything that is not an owned
  dependency of the alerting service. A misspelled name is refused, not sent.
- **One paid recording** → rehearsed free first on fabricated answers, as
  `bad-deployment` was, so the paid run is spent on the model's judgement rather
  than on discovering the plumbing.

## Migration Plan

1. The demo app: `io-pricing` as a seam on the account page path, its own
   process clock, its restart through the Argo CD stand-in, the catalogue
   endpoint, and the scenario. Its own tests after the code, as that repo's
   policy has it.
2. The read tier: the catalogue tool and its typed client function.
3. `argus_core`: the mode, its meaning, the catalogue contract type, and
   `faulting_service` on the hypothesis, with revision `001` edited in place.
4. The Investigator: the answer tool's schema and the prose obliging an address.
5. Mitigation: the strategy, its registration, the blast-radius gate, and the
   narration sentence.
6. The write tier: the per-service resource name and the per-service
   confirmation, with `test_all` green as the evidence that the shop's own
   restart is unchanged.
7. The e2e case, rehearsed free.
8. One `record(mode='both')` for the new case, then green under `e2e_replay`.
9. The docs: spec §7.3 and §13, and the backlog's propagation row.

## Open Questions

- Does the catalogue belong to the Target Service or to the platform stand-in?
  It is served by the demo app either way, but the route decides which fiction
  it lives in - a service registry the organisation keeps, or something the
  shop reports about itself. The registry reads truer, since the whole point is
  that it is maintained centrally and nobody looks at it.
- Does `slow-canary-rollout` or `cache-misconfigured` need a catalogue entry to
  stay coherent once one exists? A catalogue that only ever mentions two
  dependencies is one a reader will notice is a prop.
- Is the blast-radius refusal published in the same place as the two existing
  silences at the gate, or is it a third? It is a third sentence, and
  `generic-mitigation-tier`'s requirement about distinguishing silences is where
  it has to be written down.
