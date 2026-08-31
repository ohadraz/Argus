## Context

The mitigation walk has three exits and five statuses, and two of them are
currently crossed.

`mitigation_node` ends by calling `_status_after(verdict)`, which maps
`REFUTED` to `FIXING`. That value is persisted by `transition_incident`,
published as a `StatusChanged` event, and returned into the graph state - and
then `route_after_mitigation` reads `FIXING` and routes to `next_candidate`,
whose first branch immediately transitions the same incident back to
`MITIGATING`. So `fixing` exists in the record for the length of one node, and
means "a refuted action is looking for the next candidate", which is not what
it is named after.

At the other end of the same walk, `next_candidate_node`'s exhausted branch
transitions to `ESCALATED` and `route_after_next_candidate` sends `escalated`
to the `codefix` node. An incident entering Code-Fix is therefore recorded as
escalated - a terminal status by `is_terminal` - while Argus is about to look
for a permanent fix.

The two errors have hidden each other. The graph routes correctly today, so
every test passes; only the persisted status and the published event are wrong,
and the incident timeline and the dashboard badge are the readers that see it.

## Goals / Non-Goals

**Goals:**

- A refuted mitigation self-loops on `mitigating`, writing no intermediate
  status.
- An incident entering Code-Fix is recorded as `fixing`.
- `escalated` is written only where a human is being handed the incident.
- The graph's routing behaviour - which node runs after which - is unchanged.

**Non-Goals:**

- Building the Code-Fix agent. `codefix_node` stays the stub it is; this change
  only corrects the status the incident wears when it arrives there.
- Any change to `IncidentStatus`'s members, the database column, or historical
  rows. Incidents already written with the old values keep them.
- Revisiting when the page is raised. The Communicator's trigger is unchanged.

## Decisions

**Route on the status, keep the route names.** `route_after_mitigation` keys on
`FIXING` to mean "next candidate"; after the change it keys on `MITIGATING`.
The returned route *names* (`resolved`, `next_candidate`, `escalated`) and the
edge map in `build_graph` stay as they are, so the diff is confined to the
predicate and the graph's shape is provably untouched.

Considered and rejected: introducing a separate `verdict`-keyed router that
does not consult status at all. It would be a cleaner separation - the route is
a function of the verdict, and status is a function of the route - but it
splits the walk's control flow across two representations at a moment when the
whole point is that status and control flow disagreed. Keeping one source and
correcting it is the smaller, checkable change.

**`route_after_next_candidate` gets a `fixing` branch rather than reusing
`escalated`.** The exhausted branch writes `FIXING` and returns the route name
`fixing`, mapped to the `codefix` node. `escalated` remains a route name out of
this node for the case where there is genuinely nothing - it is currently
unreachable once the exhausted branch claims `fixing`, so it is removed rather
than left as a branch no input can produce.

**`is_terminal` is unchanged in behaviour, corrected in reasoning.** `FIXING`
was already excluded from the terminal set, but the docstring justifies it as
"where a refuted action goes to ask whether another candidate is left", which
stops being true. The set is right for the new reason: Code-Fix is working.

**The three-line `_status_after` collapses to two cases.** `CONFIRMED` →
`RESOLVED`, `REFUTED` → `MITIGATING`, anything else → `ESCALATED`. Worth
keeping as a named function rather than inlining: it is the one place the
verdict-to-status mapping is stated, and this change is evidence that having
one place matters.

## Risks / Trade-offs

**A refuted action now returns the status it arrived with, so a reader of
`mitigation_node`'s return value cannot tell "refuted, trying again" from
"nothing happened".** → The `StatusChanged` event is still published, carrying
`result.detail`, and `record_outcome` still writes `refuted` against the
candidate's own row. The verdict, not the status, is where "what happened" is
recorded, and that is unchanged.

**A self-loop on `mitigating` makes the status alone insufficient to detect a
stuck walk.** → It already was: the walk's bound is `candidate_index` against
the candidate list and `rounds` against `investigation_max_rounds`, both in
state and both unchanged. A status that changed on every attempt would have
looked like progress without being a bound.

**e2e assertions that wait for a terminal status could now wait through
`fixing` where they previously saw `escalated`.** → `is_terminal()` already
excludes `fixing`, so a poller using it behaves correctly; one comparing
against a literal set of statuses would not. The e2e suite is checked for the
latter as part of implementation.

## Open Questions

None. The change is local to two functions, one predicate and one docstring.
