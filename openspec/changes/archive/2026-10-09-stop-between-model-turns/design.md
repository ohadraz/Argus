## Context

A walk learns its incident is no longer wanted from `IsStillWanted`
(`argus_incidents.withdrawal`), asked in three places: before every node
(`with_status`), on each pass of Mitigation's recovery wait, and by the worker
before and after the walk. Since 26f0a92 a node that finishes after a withdrawal
cannot write over it - `incidents.transition` refuses, and `with_status` routes
out on the refusal.

What is left is the time *inside* a node. The Investigator's ReAct loop
(`agent_investigator/investigation.py`, `while True`) and Code-Fix's loop
(`agent_codefix/proposing.py`, `while not spend.bounds_reached()`) keep asking
the model and dispatching tools after a withdrawal, and Mitigation applies its
action (`agent_mitigation/trying.py`, `_perform`) without asking first - between
the node-boundary check and the write sit a claim, two publishes and, on a
resumed run, a provider read. Code-Fix's `write_branch` / `open_pull_request`
follow its loop unasked as well.

Mitigation already carries the seam this needs: `take_action` takes
`still_wanted: StillWanted` (`Callable[[], bool]`, bound to the incident by the
walk), threaded `Collaborators.still_wanted` → `graph.py` → `mitigation_node`
(`partial(still_wanted, state.incident_id)`) → `TakeAction` port → `take_action`.

No agent package depends on `argus_incidents`, and none may know another.

## Goals / Non-Goals

**Goals:**
- A withdrawal is noticed before the next model turn in the Investigator and
  Code-Fix, and before any write Argus makes to the world: Mitigation's action,
  Code-Fix's branch and pull request.
- A loop that stops for this reason is reported as stopped - not as a failure
  (the worker would record a failed run), not as "nothing found" (the walk
  would route on), not as an escalation.
- The mechanism is the one change (b) will reuse unchanged when a human
  resolution also makes an incident "no longer wanted".

**Non-Goals:**
- Interrupting a model call already in flight. It returns; its answer is not
  acted on (the existing spec scenario).
- Changing what the worker does after the walk (unwind on withdrawal). Change
  (b) decides what a resolution does there.
- Stopping an undo. Putting back Argus's own refuted change, and the worker's
  unwind, are clean-up and still complete.

## Decisions

### D1. One type, in the kernel: `argus_core.budget.StillWanted`

`StillWanted = Callable[[], bool]` moves from `agent_mitigation.tools` to
`argus_core.budget`, beside the other things that bound an agent loop, with a
default `wanted_throughout() -> bool` that always answers yes.
`agent_mitigation` keeps exporting the name (re-exported, not redefined).

*Alternatives:* each agent declares its own alias (three definitions of one
idea, the precedent `Fixer`/`ProposeFix` is a port restated for mocking, not a
domain type); a Protocol (only needed for `create_autospec`, and every existing
test of this seam passes a plain function).

### D2. Agents ask before each turn and before each write; the answer is a zero-argument callable

- Investigator: `investigate(..., still_wanted=wanted_throughout)`; asked at the
  top of each loop pass, before `speak`.
- Code-Fix: `propose_fix(..., still_wanted=wanted_throughout)`; asked at the top
  of each loop pass, before `converse`, and once more before `write_branch`.
- Mitigation: `take_action` asks before `_perform`. The resumed re-take in
  `mitigating.py` goes through `take`, so it is covered by the same check.

The agent never learns which incident it is asking about - the walk binds it,
as it already does for Mitigation.

### D3. How each agent says "stopped"

- **Investigator** returns `Findings` with a new `stopped: bool = False` set,
  carrying one undetermined candidate so `candidates` stays non-empty (its
  documented invariant, and `investigator_node` indexes `[0]`). The node, on
  `stopped`, returns an empty delta at once: no hypotheses recorded, no flag /
  deployment / register reads, no memory search, no `HypothesisFormed`.
- **Code-Fix** raises `FixStopped` (new, in `agent_codefix`). `codefix_node`
  catches it before its broad `except` and returns an empty delta, publishing no
  `FixAttempted` - nothing was attempted to an end.
- **Mitigation** returns `Outcome(verdict=WITHDRAWN, undo_descriptor=None,
  measured=False)` without performing, so `complete_action` records an action
  that changed nothing and the unwind has nothing to put back.

*Alternatives:* raising from the Investigator too (reaches the worker as a
failed run - `runs.fail` plus `logger.exception` - for something that is not a
failure); a Code-Fix return sentinel (`None` already means "no fix warranted",
which the node narrates as an outcome).

### D4. `with_status` asks once more after the node returns

An empty delta derives the status the incident already had, so no transition
is written, no refusal comes back, and the routers would carry on. `with_status`
therefore asks `still_wanted` after the node as well as before it, and on "no"
returns the node's updates with `status: withdrawn`, writing nothing. The
guarded transition (26f0a92) still closes the race where the withdrawal lands
between this read and a write.

This also stops a Mitigation that returned `Verdict.WITHDRAWN` at once, rather
than one node later at `next_candidate`.

*Alternative:* each node returns `status: withdrawn` itself - five nodes
remembering a rule `with_status` exists to hold once.

### D5. Ports grow a defaulted keyword

`Investigate` and `ProposeFix` / `Fixer` gain `still_wanted: StillWanted`,
defaulted, so every existing caller (integration tests, the eval, the effort
script) keeps working. `investigator_node` and `codefix_node` take the
walk-level `IsStillWanted` and bind the incident, as `mitigation_node` does.

## Risks / Trade-offs

- [One more database read per model turn and per node] → a primary-key read
  against a turn measured in seconds; not worth caching, and a cached answer is
  a late answer.
- [Investigator stopped after reads it already dispatched] → those reads are
  recorded in `replay_log` as made, which is accurate; nothing is buffered, so
  token and call accounting stay correct.
- [Stand-ins for the widened ports] → mypy flags any hand-written stand-in that
  lacks the new keyword; the defaulted keyword keeps `create_autospec` ones
  working.
- [Replay recordings] → unaffected: a walk nobody withdraws gets "yes" every
  time and makes exactly the calls it made when recorded.

## Migration Plan

None. No schema change, no new event kind, no recording.

## Open Questions

None.
