## Why

A refuted mitigation is a dead end. The Investigator forms exactly one hypothesis, Mitigation acts on it, and when the action does not help the incident routes straight to Code-Fix and a human - even though the evidence usually supported a second candidate the loop never got to try. The red-herring scenario shows it plainly: Argus correctly reverts the flag that changed, correctly notices the shop is still broken, correctly puts the flag back, and then stops, holding a list of one.

Being wrong about a correlated change is the ordinary case in an incident, not the exceptional one. An agent whose autonomy ends at its first wrong guess is an agent that escalates most real incidents.

## What Changes

- The Investigator returns **ranked hypotheses** - an ordered list, best first - rather than a single verdict. The model already assigns confidence; ranking is that order made explicit and carried forward instead of collapsed.
- **BREAKING** (internal): `investigate()` returns an ordered `list[Hypothesis]`, and `IncidentState.hypothesis` becomes a list plus a cursor. Every consumer that reads "the hypothesis" - the tier gate, Mitigation, Postmortem, the repository - reads "the hypothesis currently being tested".
- Mitigation **walks** the list. Each candidate gets a proposed action, the gate, the action, and a verdict. A refuted action is undone - as it already is - and **the undo is confirmed** before the next candidate is tried, so no two experiments ever overlap in production.
- When every candidate from a round is refuted, the Investigator is asked **again** - resuming the widening schedule from where it stopped, and carrying the refutations as evidence. The loop stops at its first confident answer today, so a successful investigation leaves its widening budget untouched; that budget is spent only when the cheap window's answers have actually been tried and failed.
- **No attempt cap.** The walk ends when the widening schedule reaches its maximum and a round names nothing that has not already been tried. Finite by construction, rather than by a number chosen in advance that would stop while real options remained.
- Every candidate's outcome is written to its own `hypothesis` row via the `tested`/`result` fields that already exist for it, so the timeline shows what was tried, in what order, and what each attempt did.
- The Communicator posts a **war-room update** while autonomy still has moves - what was tried, what it did, what is next - and **pages a human only when the walk runs out**. A page per refuted candidate would train its readers to ignore it.
- A next candidate whose action is **irreversible** (or carries no undo) is **posted and skipped**, not treated as the end of the walk. The gate's refusal is about that action, not about the remaining list.
- Escalation still ends the walk immediately: an action that could not be taken at all leaves the world in an unknown state, and guessing again from there is not autonomy.

## Capabilities

### New Capabilities
- `ranked-hypotheses`: the Investigator's output as an ordered list of candidates, how it is ranked, and what a consumer may assume about the order.
- `mitigation-retry-walk`: walking the candidates - undo-and-confirm between attempts, which outcomes continue the walk and which end it, and what happens when the list is exhausted.
- `investigation-rounds`: re-investigating after a round is exhausted - resuming the widening schedule, carrying refutations as evidence, and the terminus that ends the walk for good.

### Modified Capabilities
- `llm-hypothesis-generation`: the model's verdict carries alternatives rather than one answer.
- `incident-lifecycle`: `mitigating` becomes a state the incident can re-enter, and the transitions out of it depend on whether candidates remain.

## Impact

- `argus_core`: `Verdict` gains alternatives; `Hypothesis` gains rank; `IncidentState` carries the candidate list and cursor. The `hypothesis` table gains a rank column - it already stores one row per hypothesis.
- `agent_investigator`: `investigate()` returns a list, and can be resumed - it takes where the widening schedule stopped and what has already been refuted, so a later round starts wider rather than starting over.
- `agent_mitigation`: `propose_action` unchanged; the walk itself is orchestration, not the agent's.
- `orchestrator`: `graph.py` gains the loop edge - refuted returns to the proposal node with the cursor advanced - and Code-Fix is reached only once the list is spent.
- `agent_communicator`: gains the distinction between a war-room update and a page.
- `anthropic_double`: recordings gain alternatives; existing ones must keep replaying, as they did when `subject` was added.
- e2e: the red-herring case's expectation changes - it currently asserts `fixing` after a single refuted action.
