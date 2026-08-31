## Context

Five nodes decide and persist status today: `tier_gate_node`,
`investigator_node`, `mitigation_node`, `_nothing_to_act_on`, and
`next_candidate_node` (three branches). Each calls `transition_incident`, which
is `incidents.transition` - one function that does two things in one
transaction: `UPDATE incident SET status` and `INSERT INTO timeline_event`.

Everything each of them needs to reach its decision is already in
`IncidentState` before the decision is made. The Investigator compares
`hypothesis.confidence` against the mitigate threshold. Mitigation reads the
verdict returned by an action that measured re-queried metrics. The walk
compares `candidate_index` against `candidates`, and `rounds` against
`investigation_max_rounds`. None of it needs the node's private context; all of
it is state.

One case is not like the others. `tier_gate_node` rejects an action and calls
`transition_incident` with status `mitigating` - which is the status the
incident was already in. It is not transitioning anything. It is writing a
timeline note, using the only function available for writing to the timeline.

## Goals / Non-Goals

**Goals:**

- One pure function is the definition of the FSM, and it is the only thing that
  decides status.
- Nodes return their work and their narration, and nothing else.
- A status is persisted and published exactly once per actual change, as a
  property of the graph rather than a rule nodes follow.
- Narration survives independently of whether the status moved.

**Non-Goals:**

- Changing which status any incident reaches. The values are those the paused
  `refuted-mitigation-self-loop` change establishes; this change moves where
  they are decided, not what they are.
- Building the Code-Fix agent. `codefix_node` gains an honest return value and
  stays a stub.
- Anything that consults a model. The reducer is pure and stays pure - see the
  first decision.

## Decisions

**The reducer is a pure function, not an agent.** Status is a conclusion drawn
from evidence that was *measured* - a verdict from re-queried metrics, a
confidence against a threshold, an index against a list. A model asked to
re-derive it would be second-guessing evidence with prose, and would make the
one part of an incident that must be auditable and reproducible depend on a
sampled call. It would also be asked the same question after every node, which
is a model call per traversal for an answer already determined.

Considered and rejected: an LLM "status agent" that reads the incident so far
and judges where it stands. The appeal is that it could catch a case the FSM's
authors did not foresee. The cost is that it could also miss one they did, and
"the incident is resolved" is not a claim to reach by inference when
`Verdict.CONFIRMED` already means it was checked.

**The reducer lives in `argus_core`, beside `IncidentStatus`.** It is a fact
about the state machine, like `is_terminal()`, which already lives there for the
same reason. `IncidentState` is also an `argus_core` model, so the dependency
runs the right way. Putting it in `orchestrator` would make the FSM's definition
a private detail of the thing that executes it, and `argus_web` would keep
re-deriving status meaning from templates.

**Split `transition_incident` into a transition and a note.** The gate's
rejection is the proof that these are two operations: it writes a timeline row
with an unchanged status, because narration and transition were only ever the
same function by accident. `incidents.transition` keeps its current contract -
`UPDATE` plus the paired row, used only when the status actually changed - and a
new `incidents.record_note` writes a timeline row alone, carrying the status the
incident is already in. The single-writer rule (spec §7.1, §11.1) is unaffected:
both are the Orchestrator writing.

**A wrapper at registration time, not a call inside each node.** `build_graph`
wraps each node function: run the node, merge its updates onto the state, apply
`status_after`, and if the result differs from the status the node was entered
with, call `incidents.transition` and publish `StatusChanged`. A node that
returns a narration line gets `record_note` called for it either way.

The `Actor` comes from the wrapper's registration, because which agent a node
belongs to is fixed when the graph is built and was being repeated inside every
`transition_incident` call as a constant. The narration comes from the node,
which is the only thing that knows what it just did. The status comes from the
reducer.

Considered and rejected: a separate status node inserted between every pair of
existing nodes. It doubles the graph's node count, doubles the checkpoint
writes, and makes the edge map unreadable - and LangGraph gives no way to say
"after every node" except by wrapping, so the wrapper is the honest expression
of the same idea.

**The Investigator reports that a round found nothing actionable, and the state
carries it.** The Investigator and the walk ask the same question -
`_the_next_worth_trying` - and answer differently when it is no: the
Investigator escalates, the walk buys another round if the budget allows. That
is deliberate, not an inconsistency. The Investigator's ReAct loop has already
widened its window as far as it can within the round, so a re-investigation on
the same evidence would spend model calls to reach the same answer; the walk, by
contrast, has just learned something a re-read cannot produce - that a change
was made to production and did not help.

From the resulting state alone those two moments are indistinguishable: both
leave a candidate list with nothing actionable in it. So `IncidentState` gains
`nothing_worth_trying: bool`, set by `investigator_node` on every round. It is a
fact about what the investigation found - work the node did - not a status it
decided, which is the line this change draws.

Considered and rejected: unifying the two rules so an investigation with nothing
actionable also buys another round. It would need no new field, but it spends
`investigation_max_rounds` model calls on incidents the Investigator has already
said it has nothing for.

**The reducer reads outcomes, never re-derives them.** With
`nothing_worth_trying` explicit, `candidate_index < len(candidates)` is
sufficient to mean "a candidate is under test": every node that sets the index
sets it to something worth trying, or past the end. `_the_next_worth_trying`
therefore stays private to `orchestrator` and the reducer never runs the search
a node already ran. In order:

1. a code fix was attempted - `resolved` if one was found, `escalated` if not
2. the action outcome is `confirmed` - `resolved`
3. the action outcome is `escalated`, meaning it could not be taken - `escalated`
4. the investigation found nothing worth trying - `escalated`
5. a candidate is under test - `mitigating`
6. rounds remain - `investigating`
7. otherwise - `fixing`

**`route_after_*` predicates are unchanged.** They read status and return a
route. That was always the right shape; it was only unreliable because status
was unreliable.

## Risks / Trade-offs

**The reducer must be total, and a state it has no rule for silently gets some
default.** → It returns `IncidentStatus` with no fallback branch: every path
ends in an explicit return, and the exhaustiveness is asserted by tests over the
state combinations each node can produce. A state the FSM has no answer for
should be a failure, not an `escalated` that looks like a decision.

**`IncidentState` grows two fields for the reducer's benefit
(`nothing_worth_trying`, and whatever `codefix_node` reports), which looks like
leaking the reducer into the model.** → Both are facts about work that was done,
which is what the rest of `IncidentState` already is - `action_outcome` and
`can_widen` are the same kind of thing. The test is whether a field would still
be worth recording if no reducer existed, and a human reading an incident wants
to know that a round found nothing actionable either way.

**Wrapping every node changes what unit tests can call.** → Node functions stay
public and directly callable, and lose a responsibility rather than gaining one;
their tests assert the work and the narration. The reducer gets its own tests,
which is the point - the FSM becomes testable without constructing a graph.

**A large diff in the one file the last two changes also touched.** → The paused
`refuted-mitigation-self-loop` is 13/15 and its remaining tasks are `lint`,
`typecheck` and `e2e_replay`. Its code edits are the starting point for this
one, not a conflict: this change moves those decisions rather than reversing
them.

## Migration Plan

No data migration. `timeline_event` gains rows that repeat the previous status
(notes), which readers already tolerate - the incident timeline renders rows in
order and does not assume each one differs from the last.

## Open Questions

- Whether `postmortem_node` and `communicator_node` should narrate through
  `record_note` as well. They write no status today and are silent in the
  timeline; making them narrate is in the spirit of this change but is
  additional behaviour, not a refactor. Deferred unless it falls out for free.
