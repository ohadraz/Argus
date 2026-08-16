## Context

Nothing exists in `modules/` yet. The spec (`docs/spec-and-architecture.md`) locks in a 5-agent architecture orchestrated by a LangGraph `StateGraph` (§7.1, §10) with Postgres-backed state (§11.1), but none of it has been exercised in code. This design covers the smallest slice that proves the architecture connects: one real end-to-end path through every state in §10's FSM, with every module boundary from §20.2 actually instantiated as a workspace package - but with every sub-agent's *internals* stubbed to trivial, hardcoded behavior. No ReAct loop, no MCP tool calls, no LLM calls anywhere in this change.

## Goals / Non-Goals

**Goals:**
- Every module in spec §20.2's tree that participates in the
  incident lifecycle exists as a real `modules/<name>/` workspace package with a real `pyproject.toml`.
- The LangGraph `StateGraph` from §7.1 is real, with real
  conditional edges implementing §10's FSM - not a mock, not a diagram, an actual graph that actually runs.
- `IncidentState` (§11.1) is a real Pydantic model, actually
  persisted to a real Postgres instance via LangGraph's checkpointing (§7.1), with `TimelineEvent` rows actually written
  on every transition (§10's own requirement, restated in §11.1's dual-write rule).
- One full path - `investigating → mitigating → resolved` - runs 
  end-to-end from a webhook call, through every sub-agent node, to a stub `Postmortem` row, without manual intervention.
- A single human-authored e2e test (§18.2, §20.2) in `tests/e2e/`
  proves the path: POSTs a realistic third-party alert webhook (Grafana's unified-alerting format) to the webhook endpoint, then asserts directly against Postgres - an `INCIDENT` row at `status=resolved`, a `TIMELINE_EVENT` row per transition, and a stub `POSTMORTEM` row. This test is the change's definition of "done"; per §18.3, the AI coding agent implementing this change does not write it.

**Non-Goals:**
- Any real ReAct loop, hypothesis reasoning, or LLM call (§9) -
  Investigator's stub just returns a hardcoded high-confidence hypothesis.
- Any real MCP server, tool integration, or Target Environment
  (§12, §15) - Mitigation's stub "action" is a no-op that immediately reports `confirmed`.
- The `escalated` or `fixing` FSM branches (§10) - only the 
  straight-through `investigating → mitigating → resolved` path is exercised in this change. Escalation and Code-Fix are real sub-agents with real stub nodes (so the graph's shape is complete), but the *paths* that would route to them are not driven end-to-end yet.
- The tier-gate node (§13) doing real enforcement - it exists as a
  pass-through node in the graph (so the graph's shape matches §7.1), but doesn't yet block anything.
- Slack, email, or any Communicator output beyond a stub call - no
 real external service.
- Dashboard, Backoffice, Vault, Chroma - out of scope entirely for
  this change.
- **Generic, format-agnostic alert ingestion.** This change's
  `argus_web` webhook handler parses exactly one hardcoded shape (Grafana's unified-alerting format, matching the e2e test) into the `Alert` domain object via a plain deterministic parser - not an LLM call, not a per-vendor adapter registry. Handling arbitrary reasonable third-party formats generically (via LLM-based structured extraction at the boundary, not a ReAct loop) is real future work, tracked in spec §7.9/§25 - deliberately deferred so this change proves graph/DB/checkpointing wiring without also taking on LLM-extraction-reliability risk in the same change.


## Decisions

**LangGraph from the start, not a hand-rolled state machine stubbed in first.**
Spec §7.1 already locks in LangGraph specifically for its conditional-edge mechanism and built-in Postgres checkpointing - both are exactly what this walking skeleton needs to prove (the graph resuming from a checkpoint is itself part of what "the architecture connects" means). Building a throwaway hand-rolled FSM first and swapping to LangGraph later would mean proving the wrong thing now and redoing the proof later. Alternative considered: a plain Python state machine (dict of transitions) for the skeleton, deferring LangGraph to a later change - rejected because it wouldn't validate the actual architectural risk (LangGraph's checkpointing behavior), only a simplified stand-in for it.

**Every sub-agent module is scaffolded now, even ones this change's single happy path doesn't drive.** Code-Fix and the `escalated`/`fixing` branches aren't exercised end-to-end here (Non-Goals above), but `modules/agent_codefix/` still gets created as a real workspace package with a stub node wired into the graph's edges - just not called by the one path this change proves. Alternative considered: only scaffold the three modules the happy path touches (Investigator, Mitigation, Postmortem), adding Code-Fix/Communicator later - rejected because the graph's edge *shape* (§10's full FSM, including branches to `fixing`/`escalated`) is itself part of what needs proving now; a graph missing edges to nonexistent nodes isn't the same graph the spec describes.

**Stub nodes return hardcoded values, not randomized or configurable ones.** Investigator's stub always returns the same fixed hypothesis at fixed confidence above the §10 threshold (0.75); Mitigation's stub always reports `confirmed`. This keeps the one proven path fully deterministic - a walking skeleton's job is to prove wiring, not behavior, so nondeterminism here would only make failures harder to reproduce without adding any signal.

**A real Postgres instance, not an in-memory/SQLite stand-in.** §11.4 already reasons at length about why operational state needs Postgres specifically (row-level locking, transactions, joins for eval metrics). Using SQLite "just for now" would risk the walking skeleton proving a data layer the real system doesn't use. `docker-compose` already exists as a concept in the spec (§19); this change adds a minimal Postgres service to `docker-compose.yml` at the repo root - the one file this change touches outside `modules/*`.

**The proving test lives in root `tests/e2e/`, not inside any single module's `tests/`.** It spans all 8 modules and exercises the real `docker-compose` stack (HTTP webhook call, real Postgres) - matching §20.2's definition of `tests/e2e/` ("full stack via docker-compose... end-to-end"). It isn't a per-module unit test (§18.4) since no single module owns the full path, and it isn't `tests/integration/` since that's for in-process module interaction, not the deployed stack this change needs to validate. Written by a human first, per the TDD workflow (§18.2) - the AI coding agent proposes it as text/diff only (§18.3), never writes it directly.

## Risks / Trade-offs

- **[Risk]** A LangGraph checkpointing detail (e.g.,
  resume-after-restart semantics) turns out not to work as §7.1 assumes → **Mitigation**: this is precisely the risk a walking
  skeleton is meant to surface early; finding it now costs one change, finding it after five real sub-agents are built costs a rearchitecture.
- **[Risk]** Scaffolding eight modules at once (`argus_core`, 
  `argus_web`, `orchestrator` and five sub-agents) is a lot of surface for one change → **Mitigation**: every module's internals are trivial by design (Non-Goals above); the size is in module *count*, not module *complexity*.
- **[Risk]** `docker-compose` Postgres wiring for this change might
  not match what `nox -s e2e` (already existing, currently only used for root `tests/e2e/`) eventually needs → **Mitigation**: flagged as an explicit open question below rather than guessed at.

## Migration Plan

N/A - net-new modules, nothing existing to migrate. Rollback is just deleting the new `modules/*` directories and reverting the added Postgres service in `docker-compose.yml` - the only file this change touches outside `modules/*`.

## Open Questions

- This change adds a Postgres service to `docker-compose.yml`. Does
  it reuse/become the same service `nox -s e2e` (already in `noxfile.py`) brings up, or stay a separate one scoped to local dev?
