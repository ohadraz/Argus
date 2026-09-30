## Context

`agent_mitigation.trying` performs one proposed action and judges what the
service did. It handles two kinds of failure today. `ActionExhausted` is caught
first and deliberately - the platform answered, and its answer is that this
action has nowhere left to go - and everything else falls to a broad
`except Exception` that returns `Verdict.ESCALATED` with the exception's text in
its detail ([trying.py:176-206](../../../modules/agent_mitigation/src/agent_mitigation/trying.py#L176-L206)).

A control plane failure lands in that second branch. So an incident whose
rollback cannot reach Argo CD ends immediately, on its first candidate, having
established nothing about why - and the escalation a person reads is a transport
error about one action.

Four of the five declared mitigations reach the estate through Argo CD
(`rolling_back`, `restarting`, `scaling`, `pinning` all read `argocd_base_url`);
only `flag_state` goes to Unleash. So the failure is not one action's and not the
whole set's - it is four of five, and which four is a fact about the action kinds
rather than about the incident.

The walk's own machinery is closer to ready than it looks. Candidate advance is
by index ([state.py:191](../../../modules/orchestrator/src/orchestrator/walk/state.py#L191)),
`NEXT_CANDIDATE_ROUTE` already exists, and
`candidates.what_each_would_do` already asks Mitigation which action answers each
candidate - which is exactly the point at which a candidate's platform can be
read off without asking anything new.

## Goals / Non-Goals

**Goals:**

- Tell an unreachable platform apart from an action that failed, at the point
  where the difference is knowable: the write tier.
- Narrow the walk to what is still reachable, rather than ending it.
- Leave a record that says the platform was unreachable, so that an incident
  mitigated by the one action on a live platform does not read as a preference.
- Stage it end to end in the Target Environment, with the shop staying healthy.

**Non-Goals:**

- Diagnosing the control plane. Argus has no mitigation for Argo CD itself and
  is not being given one; it discovers unreachability by reaching for something,
  and never investigates it as a cause.
- Distinguishing *why* the platform is unreachable - refused, timed out, `503`.
  All three mean the same thing to the only reader that matters, which is the
  walk deciding what it can still do.
- Retrying. A platform that refused this call will refuse the next one seconds
  later, and probing it until it answers is not the walk's job. Worth being
  honest about the cost: a retry would be one HTTP round trip, not a
  verification window - the broad `except` in `trying.py` returns before
  `_what_watching_the_service_settled` is ever called, so a failed action never
  reaches verification at all. The reason not to retry is that it buys nothing,
  not that it is expensive.
- Reachability as a thing checked ahead of time. Nothing polls Argo CD to ask
  whether it is up; the fact is learnt by an attempt, which is the only way it is
  ever true at the moment it is acted on.

## Decisions

### An unreachable platform is a marked error, not a new transport

It reuses the mechanism `ActionExhausted` already established: the server raises
an error carrying a marker, `argus_core.mcp_transport` recognises the marker and
re-raises a typed exception, and the caller catches that type ahead of the broad
`except`. The ordering in `trying.py` is load-bearing in exactly the way the
existing comment says it is - a broader `except` reached first swallows it.

*Alternative considered:* let `trying.py` inspect the exception it already
catches - sniff for `httpx.ConnectError`, a `503`. Rejected: the mitigation agent
would then know which library the write tier calls the platform with, which is
the boundary the MCP tier exists to hold. The tier that made the request is the
only one that can say what the request did.

### A platform lost mid-action is still a platform lost, and carries what landed

Two of the four actions change something before the thing they were asked for.
A rollback and a scale-out suspend the platform's own reconciliation first -
they are refused otherwise - so a platform that stops answering after that point
has left an application un-reconciled.

The tempting rule is that only a failure which changed nothing may be marked, and
everything else escalates. It is wrong, and it is wrong in the way this whole
change is about: it handles the platform failing on the first call and not the
platform failing on the second, so a walk would narrow itself or not depending on
which call the outage happened to land on. A scale-out is where a mid-action
failure is *most* likely, not least.

So a marked failure may carry an undo descriptor. The walk then narrows - the
platform is down, and the other three actions through it are unavailable however
far into one of them the outage arrived - and the action row still records what
has to be put back, which is what any other action that changed something does.

This supersedes the "only a failure that changed nothing" restriction rather than
breaking it. That rule existed because a failure had no way to say what it had
changed; it now has one. `ActionExhausted` keeps the restriction untouched - an
exhausted action genuinely changed nothing, and that is what the type means.

The replacement has two clauses, and the second is the load-bearing one:

1. **A marked failure says what it left behind.**
2. **An action that may have taken effect, and whose effect cannot be
   established, does not mark.**

The second is not about descriptors. A restart carries no undo descriptor even
when it succeeds - `RESTART_SERVICE` is absent from `_LEAVE_SOMETHING_TO_PUT_BACK`
- so its absence says nothing unusual. What disqualifies it is that the platform
accepted the action and then stopped answering, so Argus cannot say whether a
restart is happening. A walk that narrowed there and took the flag revert would
measure recovery against a service that may be coming back from the restart, and
a confirmed flag revert might be confirming the restart's work - a wrong
conclusion written into the record as a confirmed hypothesis, which is worse than
an escalation.

The suspension cases do not have that problem, which is what makes the split
right rather than convenient. A suspended reconciliation changes what the
platform will re-apply later; it does not change how the service behaves now, so
the next action's verification still measures what it claims to.

The mechanism is the existing marker doing more work, not a new one: the marker
is already a convention over the one string a tool may fail with, and the
descriptor is serialized after it and parsed back where `isError` becomes an
exception. `Outcome` already carries an `undo_descriptor` and `unwinding` already
puts changes back, so everything downstream of the parse exists.

### Unreachability covers connect failure, timeout, and the platform's own 5xx

One typed failure for all three. A reader who is deciding what can still be
acted through gets the same answer from each, and three names would be three
branches at every call site that means the same thing.

*Alternative considered:* a hang past `REQUEST_TIMEOUT_SECONDS` as the only true
unreachability, with `503` treated as the platform answering. Rejected on both
sides: a `503` from an API server's ingress is what a downed Argo CD actually
looks like, and staging the scenario as a hang would add ten seconds per attempt
to every walk that runs it.

### The platform is a property of the action kind

A map from `ActionType` to the platform it acts through, in
`argus_core.models.action` beside `_LEAVE_SOMETHING_TO_PUT_BACK` - which is the
same shape of question asked of the same tag, and for the same reason: the walk
holds a kind, not the action it came from.

It has to be answerable for candidates that were never attempted, so it cannot
be derived by watching one fail.

*Alternative considered:* end the mitigation phase on an unreachable platform,
as the sixth `Refusal` ends it. Rejected, and this was the live fork. It is the
simpler change and produces the identical walk in the scenario below - but it
answers "four actions are gone" with "all actions are gone", and an incident
whose next candidate is a flag revert would escalate for no reason. A walk that
reads an unreachable Argo CD and stops has learnt the scenario rather than the
mode, which is the thing this change exists to avoid.

### A verdict of its own, not `NOT_ATTEMPTED`

`Verdict` already discriminates *why* no verdict was reached - `ESCALATED`,
`WITHDRAWN` and `NOT_ATTEMPTED` are three reasons for one outcome, each with its
own paragraph saying which. A fifth reason is the shape this enum already has.

`NOT_ATTEMPTED` is pinned to one of those reasons in so many words: the action
was "refused by the tier that performs it, because the action itself is
exhausted"
([action.py:29-33](../../../modules/argus_core/src/argus_core/models/action.py#L29-L33)).
Folding an unreachable platform into it would make it the first member covering
two reasons, and would force that paragraph to stop saying what it says.

Both continue the walk, so this buys nothing in routing. It is not a
documentation problem either - the enum's whole job is to carry the reason.

### Nothing reachable remaining escalates - by redirecting the tail, not by a new branch

Passing over candidates advances the index, and an index past the end of the list
today routes to a further investigation round or to Code-Fix
([state.py:188-197](../../../modules/orchestrator/src/orchestrator/walk/state.py#L188-L197)).
That is wrong here: another round would re-read the same evidence and arrive at
candidates that act through the same dead platform.

So the unreachable platform is carried on the walk's state, and it turns that
past-the-end tail - `INVESTIGATING` where rounds remain, `FIXING` otherwise -
into `ESCALATED`. The index check at
[state.py:191](../../../modules/orchestrator/src/orchestrator/walk/state.py#L191)
stays first.

**Not a branch before the arithmetic**, which is the trap and was this design's
own first answer. "Set, and nothing confirmed" is true the instant the rollback
fails - at which point the flag revert is still ahead at a valid index and the
incident should read `MITIGATING`. Asked before the index check it would return
`ESCALATED` mid-walk and break this change's own scenario. Redirecting the tail
cannot fire while a reachable candidate remains, which is the property that
makes it correct rather than merely smaller.

This is the one place the change touches status derivation.

### One event, naming the platform and what it took away

Published where the unreachability is first learnt, not per candidate passed
over. The reachability spec carries the cardinality rule; the shape is a platform
and the action kinds that platform carries, so that the narrated line can say
what is unavailable rather than what was skipped.

### The scenario needs two platforms in one window

A deployment and a flag both moved, deployment ranked first. Anything less
cannot tell this design from the one it replaced: a cause whose every candidate
acts through Argo CD escalates under both, and the case would pass without
exercising the fall-through.

The deployment ranked first is load-bearing too - a flag revert already at the
top would be taken before Argo CD was reached for at all.

### Only the routes that change something refuse

The deployment platform's *reporting* routes keep answering. `/argocd/*` is not
only the write path: `GET /argocd/{application}` is the deploy-history endpoint
the read tier's `fetch_argocd_application` reads for the deployment change
channel, over the same `argocd_application_path` setting the write tier uses.

Refusing the prefix wholesale would hide the deployment that is this incident's
first candidate. No rollback would be ranked, the walk would never reach for the
platform, and the case would pass green having exercised none of this. So the
switch refuses the acting routes - rollback, restart, resource write, spec - and
leaves the reads alone.

It is also the truer staging. This change is about a platform Argus cannot act
*through*; a platform it cannot *see* is a different mode, and one nothing here
addresses.

## Risks / Trade-offs

- **The scenario's ranking is not ours to fix.** Whether the rollback outranks
  the flag revert is the model's judgement over the evidence, so the scenario
  has to make the deployment the more plausible cause rather than assert the
  order. → Stage the deployment as the closer and more specific change, and
  confirm the ranking in the recorded walk before the e2e case rests on it. If
  the model ranks the flag first, the recording is what says so, and the
  scenario's staging is what changes.
- **The plane map is a second place the action kinds are enumerated.** It will
  be missed when a sixth mitigation is added. → An exhaustive mapping over
  `ActionType` rather than a `dict` with a default, so a new kind fails the type
  check rather than silently acquiring a platform.
- **`503` is also what a healthy platform says under load.** Treating it as
  unreachability means a momentarily overloaded Argo CD takes four actions off
  the table for the rest of the incident. → Accepted, and this is the weakest
  call in the file. The alternative is a retry, which this does not do because it
  buys nothing rather than because it costs anything - see the Non-Goal. What
  bounds the damage is that the flag is carried per incident, so a walk pays for
  one bad read and the next incident starts clean.
- **The skip is invisible in the incident's timeline** unless the event lands
  before the fall-through's own events. → The event is published where the
  unreachability is learnt, which is before the next candidate is proposed.
- **A recording per mode is a walk per mode, for ever.** → One recording under
  `both`, by the reasoning already written into `_the_cases_for`: nothing in this
  claim varies by which tool found a file.

## Migration Plan

No data migration. The new event is additive to the stream, the new verdict is
additive to an enum nothing persists exhaustively, and no existing incident
record changes shape.

The order that keeps every step verifiable for free:

1. The marker, the exception and the platform map - unit-tested, nothing running.
2. The write tier raising it - its own suite, against a stubbed platform.
3. The walk catching it, passing over same-platform candidates, and escalating
   where nothing remains - `agent_mitigation` and `orchestrator` suites.
4. The event and its narrated line.
5. The Target Environment's switch, and the shop staying healthy under it.
6. The e2e case, run under replay against a recording made last.

The recording is last and is the only paid step.

## Open Questions

None outstanding. Two were open and both are closed:

- **The narrated line names the actions**, not just the platform. The
  brittleness that argued against it is already paid for by the exhaustive
  `ActionType` map: generate the line from it and a sixth mitigation fails the
  type check rather than leaving a stale sentence behind. A platform name alone
  makes the reader go and look up what it cost them, which is the thing the event
  exists to prevent.
- **The read tier is left alone**, and the scenario's route split is why that is
  coherent rather than merely convenient. A read that fails is a different mode:
  the change goes unseen, no rollback is ranked, and the incident becomes one
  about detection. Same platform, same failure, different reader - and nothing
  here addresses it.
