## Context

The FSM already drives `investigating -> mitigating -> resolved`, and the
mitigation node already records an `action` row and a status transition. What is
missing underneath it is everything real: `mitigate()` returns `"confirmed"`
without acting, `argus-write-mcp` does not exist, and the `undo_descriptor`
column on `action` has never been written to.

Two things now make the honest version possible. The Target Service's telemetry
is a read-time function of live flag state, so changing the flag genuinely
changes the next `/metrics` response - a verdict can be measured. And onset
detection is now robust enough on that generated telemetry to say whether a
window has departed from baseline at all, which is the same judgement recovery
needs, read the other way round.

Spec §12.1 describes the write tier's full surface - flag toggle, git revert,
pull request, Slack, email, memory write. This change builds one tool of it. The
tier split is the point, not the tool count: once a second process exists holding
the write credentials, every later tool lands in a place whose autonomy
properties are already established and tested.

## Goals / Non-Goals

**Goals:**

- A `argus-write-mcp` process that is structurally incapable of read-tier
  privilege confusion: it holds the flag provider's admin credential, and
  `argus-read-mcp` holds only the evaluation credential.
- One reversible action, end to end: put the feature flag back to the state it
  held before the change that caused the incident - in whichever direction that
  is - carry the undo descriptor, verify recovery from re-queried metrics, and
  return confirmed or refuted.
- The Orchestrator's gate node from §13, enforcing that no reversible action
  reaches its MCP call without a populated undo descriptor.
- An e2e case that asserts the *world* changed - the flag is off, the error rate
  fell - not merely that Argus reported success.

**Non-Goals:**

- `push_revert_commit`, `open_pull_request`, Slack, email, memory write. Each
  needs its own vendor integration and none is unblocked by this change.
- The `bad-deployment` scenario's mitigation. It has no controllable condition
  until the git write path exists; it stays diagnosable and unmitigable.
- Vault (§14). Credentials stay in settings, as every other credential here does
  today.
- A model call anywhere in the mitigation path.
- Re-investigating after a refuted mitigation. `refuted` routes to `fixing` as
  the FSM already says; what Code-Fix does there is its own change.

## Decisions

### The write server talks to the flag provider directly, not through the Target Service

The Target Service's `/scenario/*` routes can turn the flag on and off, and using
them would be less work. It would also be a lie about what Argus is: scenario
control is the fixture's own staging seam, and an incident-response agent that
mitigates by asking the broken service to fix itself has demonstrated nothing.
Argus reverts the flag in the provider, exactly as a human would in Unleash's
console, and the Target Service finds out the same way it finds out about a
human - by evaluating the flag on the next read.

### A flag causes an incident by *changing*, in either direction

A feature flag breaks a service when its state changes, and the damaging
direction is not always "on". A flag turned off is as capable of causing an
incident as one turned on: it can disable the fallback the service depends on,
switch traffic back to a path that has since rotted, or withdraw the very
mitigation someone applied an hour ago. `cause_type=FEATURE_FLAG_TOGGLE` says a
flag was toggled - it does not say which way.

So the action is "put the flag back to the state it was in", not "turn the flag
off", and the write tier's primitive is setting a flag's state rather than
clearing it.

### Which flag changed is read from the provider's history, not from current state

Current state cannot answer this. A flag that was switched off into an incident
is off now, and so is every flag that has been off for a year - the two are
indistinguishable by evaluation. Only the change history separates them, and it
also carries the direction the action has to reverse.

So the write tier gains a second read: the flag toggles the provider recorded in
the configured environment over a recent window. Mitigation takes the latest
change per flag and sets that flag back to what it was before that change.
Exactly one flag changed is the flag; zero, or several, is not a guess to make -
it escalates, because "the evidence says a flag, and I cannot tell which" is a
real state and a human can resolve it in seconds.

The latest change per flag, rather than the earliest in the window, is what
"put it back" means when a flag was toggled more than once: the incident is
live, so the state to undo is the one the service is in now.

Alternative considered: parse the flag name out of the log prose the evidence
already contains, or ask the Investigator's model to name it as a field. Both
rejected - a hallucinated flag name is a write to the wrong flag, and the
provider knows the answer authoritatively.

### The flag history is read by the write server, not the read server

Reading the provider's event log requires an admin credential, and the flag
provider issues no read-only admin token - the credential that can read history
is the credential that can change a flag. Putting that read on `argus-read-mcp`
would hand the read tier a mutation-capable secret and dissolve the guarantee
this whole change exists to establish.

The write server already holds that credential, so the read lands there, beside
the write it informs. This does not weaken the tier split: the split is the
claim that the *read* process cannot mutate, and a read inside the write process
is strictly less capability than that process already has - the same reasoning
that already lets it evaluate flags to verify its own writes.

The cost is that the Investigator, which is read-tier, cannot see flag toggles
as change events. That channel stays deferred, and its blocker is now known to
be the provider's credential model rather than merely unbuilt work.

### Mitigation proposes; the Orchestrator gates; then it acts

Rather than one function that decides and writes, the agent exposes two steps
with the gate between them:

1. `propose_action(hypothesis) -> Action | None` - pure, no I/O, maps `cause_type`
   to a reversible action carrying its undo descriptor. `None` means no action is
   mapped, which escalates.
2. the Orchestrator's **gate node** rejects any action whose undo descriptor is
   empty, before anything mutating is called.
3. `take_action(action) -> Outcome` - performs it through `write_mcp_client` and
   verifies.

This is what makes §13's gate more than a comment: a gate placed inside the agent
that also performs the write guards nothing, because the same code could skip it.

### Recovery is measured with the Investigator's own anomaly rule, moved to `argus_core`

Confirming a mitigation is asking whether the service's recent minutes have
returned to baseline - the same departure judgement onset detection makes, asked
about the end of the window instead of its start. Duplicating that logic in
Mitigation would let the two agents disagree about whether the same minute was
healthy.

So the anomaly classification moves from `agent_investigator.anomaly` into
`argus_core`, and both agents import it. This is what the module-boundary rule
requires: shared logic belongs in `argus_core`, never copied between agent
modules or reached across them.

### A verdict waits for a completed minute

The newest metric bucket covers the minute in progress, aggregated over the
seconds elapsed so far, so reading it immediately after a revert reports a minute
that was mostly pre-revert. Mitigation polls until a bucket exists whose minute
began after the action, bounded by a configured timeout; the timeout expiring is
`refuted`, not an error - the action was taken and did not visibly help within
the time allowed, which is exactly what refuted means.

### A refuted action is undone

If the flag goes off and the errors continue, the flag was not the cause - so
leaving it off means Argus has changed production state for nothing and walked
away. The feature stays dark, nobody is told it was switched off on a wrong
hypothesis, and the next person to investigate finds an environment Argus
quietly altered.

So a `refuted` verdict restores the prior state from the undo descriptor before
the incident routes to `fixing`. This is what makes the descriptor load-bearing
rather than a record-keeping formality: it is read and acted on in the ordinary
path, not only in a recovery no one exercises.

A restore that itself fails does not silently pass. The incident escalates
carrying both facts - the action taken and the restore that did not - because an
environment left in a state Argus cannot account for is precisely what a human
needs paging for.

### The undo descriptor records the prior state, not the inverse call

`{"tool": "set_feature_flag", "flag": ..., "environment": ..., "was_enabled":
...}`. A descriptor naming the state to restore survives a tool being renamed or
resignatured; one naming the call to make does not. `was_enabled` is whichever
state the flag was actually in - false when the incident's change had switched
it off - so undoing a mitigation is the same operation in both directions.

## Risks / Trade-offs

- **Argus now holds a credential that changes production state.** → The tier
  split is the mitigation, and it is structural: the credential lives in the
  write server's configuration only, the read server is issued none, and no
  Investigator node binds a write tool.
- **A revert that coincides with recovery reads as success.** Nothing here
  proves causation - the flag went off and the errors stopped, in that order. →
  Honest scoping: `confirmed` claims the symptom resolved after the action, which
  is what §7.3 asks for. Anything stronger needs a counterfactual Argus cannot
  run on a live service.
- **Escalating on multiple changed flags will look like a regression in a demo
  where someone toggled a second flag.** → The console shows current flag state,
  and the escalation says which flags it could not choose between; the failure
  is legible rather than a silent wrong revert.
- **The provider returns its whole event log**, ignoring a row limit on the
  endpoint that reads it, so the window is applied after the fact. → Correct at
  any size and cheap at demo scale, where the log is tens of rows. A real
  deployment would need the provider's own filtering, and the adapter is the one
  place that changes.
- **Argus's own writes are indistinguishable from a human's in the history.**
  The event log attributes a change to the API token that made it, and Argus
  uses the same admin token a human would. → Accepted here: mitigation reads the
  history once, before it writes, so it cannot see its own action within an
  incident. Telling the two apart across incidents needs Argus its own token,
  which the flag-toggle change channel will want anyway.
- **Moving `anomaly` into `argus_core` touches a module with green tests for a
  reason unrelated to this change.** → It is a move, not a rewrite; the
  Investigator's own tests keep passing unchanged, which is the check that the
  move preserved behaviour.
- **`mitigate()`'s signature changes**, so the Orchestrator's mitigation node and
  its tests change with it. → Contained: one caller, and the narrowing to a
  summary string is already flagged in the node's own comment as temporary.

## Open Questions

- Does the flag-revert action belong to the incident's `service`, or to the flag
  provider's environment? Today one Target Service maps to one environment, so
  the question has no observable consequence - it will when a second service
  exists.
- Restoring a refuted revert puts the flag back on, and with it whatever the
  flag was doing - which was not this incident, or the verdict would not have
  been refuted. The trade is accepted: a wrong hypothesis should not leave a
  changed environment behind it. Whether a *second* mitigation attempt is then
  allowed, and how the loop avoids toggling the same flag repeatedly, is the
  Code-Fix path's question rather than this one's.
