## Why

Five nodes in the Orchestrator graph each decide the incident's status and each
persist it themselves. That is five places where "where is this incident" can be
answered, and they have already disagreed: a refuted mitigation wrote `fixing`
while the walk went looking for the next candidate, and an exhausted walk wrote
`escalated` on its way *into* Code-Fix. Correcting those two (the paused
`refuted-mitigation-self-loop` change) then exposed the shape of the problem
rather than the problem: `codefix_node` writes no status at all, so once the
exhausted walk stopped writing `escalated` for it, nothing did, and the incident
ended non-terminal.

Every one of these is the same bug. A node's job is to investigate, to propose,
to act - and the status is a conclusion *about* that work, drawn from evidence
the node has already recorded: a verdict measured from re-queried metrics, a
confidence against a threshold, a candidate index against a list. Asking each
node to also draw that conclusion means the state machine is defined five times
and enforced nowhere.

## What Changes

- A pure `status_after(state)` function becomes the single definition of the
  FSM. Given an incident's state it returns the status that state implies, with
  no I/O, no model call, and no knowledge of which node produced the state.
- Nodes return only their work - a verdict, a hypothesis, attempts, a proposed
  action - and a line of narration saying what they just did. They no longer
  return a `status` key and no longer call `transition_incident`.
- A single wrapper applied at node-registration time runs the node, applies
  `status_after` to the resulting state, and persists and publishes the
  transition exactly once - and only when the status actually changed. **This
  makes "a status is written only when the incident enters it" a property of
  the graph rather than a rule five nodes have to remember.**
- The `Actor` on a transition comes from the wrapper's registration, since which
  agent a node belongs to is fixed when the graph is built. The narration comes
  from the node. The status comes from the reducer.
- `codefix_node` gains a real return - whether a fix was found - so the reducer
  can conclude `resolved` or `escalated` from it. Building the Code-Fix agent
  itself remains out of scope.
- **BREAKING** for anything reading a node's return value expecting a `status`
  key. This is internal to `modules/orchestrator`; no persisted shape changes.

## Capabilities

### New Capabilities

- `incident-status-derivation`: that the incident's status is a pure function of
  its state, evaluated in one place, and that nodes do not decide it.

### Modified Capabilities

- `incident-lifecycle`: the transitions themselves are unchanged in *value* -
  this change does not move any incident to a different status than the paused
  change already puts it in. What changes at spec level is that the FSM is
  stated once and that a node is no longer permitted to write status.

## Impact

- `modules/orchestrator/src/orchestrator/graph.py` - `tier_gate_node`,
  `investigator_node`, `mitigation_node`, `_nothing_to_act_on`,
  `next_candidate_node`, `codefix_node`, and `build_graph`'s node registration.
  `_status_after(verdict)` is subsumed by the new reducer.
- A new home for the reducer. It is the definition of the state machine, not
  orchestration, so it belongs beside `IncidentStatus` in `argus_core` - see
  design.md.
- The four `route_after_*` predicates stay as they are: they read status and
  return a route, which is exactly right once status is trustworthy.
- Unblocks `refuted-mitigation-self-loop`, which resumes at its task 4.3 once
  this lands.
