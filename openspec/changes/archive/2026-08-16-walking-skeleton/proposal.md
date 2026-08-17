## Why

The spec (`docs/spec-and-architecture.md`) describes a 5-agent orchestrated system (§7, §10) but nothing has been built yet - no `modules/` exist. 
Before investing in any single sub-agent's real logic, we need to prove the core architectural shape actually connects end-to-end: webhook → Orchestrator → sub-agent nodes → back to Orchestrator, using the state machine and module boundaries already locked into the spec.
A walking skeleton validates the riskiest architectural bets (LangGraph FSM wiring, Postgres-backed `IncidentState`, module boundaries via workspace packages) with the smallest possible amount of real logic, so structural problems surface now, not after five sub-agents are half-built on top of a shaky foundation.

## What Changes

- Scaffold `modules/argus_core/`: the shared `IncidentState`
  Pydantic model mirroring §11.1's Postgres schema, plus minimal LLM/MCP client stubs other modules depend on.
- Scaffold `modules/argus_web/`: the single HTTP surface (§7.9, 
  Design Principle 7 - §4). A minimal webhook endpoint that validates the incoming alert and calls the Orchestrator's entrypoint in-process; owns no incident-domain logic itself.
- Scaffold `modules/orchestrator/`: the LangGraph `StateGraph` from
  §7.1/§10, with the tier-gate node (§13) stubbed to a no-op pass-through - no real tier enforcement yet, just the node existing in the graph. Its entrypoint creates the `Incident` row and invokes the graph (§7.1), as called by `argus_web`.
- Scaffold `modules/agent_investigator/`, 
  `modules/agent_mitigation/`, `modules/agent_codefix/`, `modules/agent_communicator/`, `modules/agent_postmortem/` as stub nodes - each accepts the shared state and returns a trivial, hardcoded transition. No ReAct loop, no real MCP tool calls, no LLM calls yet.
- Prove one full happy-path route end-to-end: webhook receipt → 
  `investigating` → `mitigating` → `resolved` (all via stub logic) → a stub `Postmortem` row - exercising that primary transition sequence in §10's FSM, with `TimelineEvent` rows actually being written. Other FSM branches (`escalated`, `fixing`, and their exits) are out of scope for this change and left for a follow-up.

## Capabilities

### New Capabilities

- `incident-lifecycle`: the incident FSM (§10) running end-to-end through stub sub-agents - webhook receipt via `argus_web`, through the Orchestrator's graph, to a resolved incident with a full `TimelineEvent` trail. See `specs/incident-lifecycle/spec.md`.

### Modified Capabilities

(none)

This capability's requirements trace directly back to sections already locked into `docs/spec-and-architecture.md` (§7, §10, §11, §20) - it doesn't introduce new architecture, only formalizes this change's slice of already-specified behavior as testable, tool-tracked requirements. See `design.md` for the explicit mapping from each stub back to its spec section.

## Impact

- New workspace members: `modules/argus_core/`, 
  `modules/argus_web/`, `modules/orchestrator/`, `modules/agent_investigator/`, `modules/agent_mitigation/`, `modules/agent_codefix/`, `modules/agent_communicator/`, `modules/agent_postmortem/` - each with its own `pyproject.toml`, picked up automatically by `noxfile.py`'s module auto-discovery (no
  `noxfile.py` edit needed, per CLAUDE.md).
- First real exercise of the TDD workflow, the `tests/` off-limits 
  policy (`AGENTS.md`, `.claude/hooks/block_test_writes.py`), and the `guard_e2e_boundary` check against actual code instead of an empty `modules/` tree.
- Requires a running Postgres instance for `IncidentState`
  checkpointing (§7.1) - local `docker-compose` service, not yet wired into `nox -s e2e`'s existing `docker compose up`.
- No changes to `docs/spec-and-architecture.md` itself.
