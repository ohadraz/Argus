## 1. The e2e test (red)

- [x] 1.1 Human-authored e2e test lives at `tests/e2e/test_incident_lifecycle.py`
  (`test_firing_alert_resolves_into_incident_with_full_timeline_and_postmortem`),
  per `AGENTS.md`/§18.3 - POSTs a Grafana unified-alerting-format webhook, then
  asserts against Postgres: the incident's `alert_payload` was normalized into
  Argus's `Alert` domain object (not Grafana's raw nesting), the `investigating
  → mitigating → resolved` transition sequence in `timeline_event`, the
  incident's final `status = resolved`, and a `postmortem` row exists
  (design.md Goal #5).
- [x] 1.2 Run it and confirm it fails (red) - nothing in `modules/` exists yet,
  `argus_web` isn't running, no Postgres service exists.

## 2. Workspace scaffolding

- [x] 2.1 Create `modules/argus_core/`, `modules/orchestrator/`,
  `modules/argus_web/`, `modules/agent_investigator/`,
  `modules/agent_mitigation/`, `modules/agent_codefix/`,
  `modules/agent_communicator/`, `modules/agent_postmortem/`, each with its
  own `pyproject.toml` (per the `new-module` skill's shape) and
  `src/<pkg>/__init__.py`
- [x] 2.2 Run `uv sync` and confirm all eight new members resolve into the
  workspace without error
- [x] 2.3 Confirm `uv run nox --list` shows a new `test_module(module='...')`
  entry for each of the eight modules

## 3. `argus_core`: domain model and Postgres schema

- [x] 3.1 Define the `Alert` Pydantic domain model (spec §7.9, §25) - the
  normalized, vendor-agnostic shape `argus_web`'s Grafana parser produces and
  the Orchestrator consumes. Fields at minimum: `service`, `alert_name`,
  matching what the e2e test asserts against `incident.alert_payload`.
- [x] 3.2 Define the `IncidentState` Pydantic model mirroring spec §11.1's
  `INCIDENT`/`HYPOTHESIS`/`ACTION`/`TIMELINE_EVENT`/`POSTMORTEM` tables
- [x] 3.3 Define the Postgres table schema for those same five tables -
  table/column names must match what the e2e test queries directly:
  `incident(id, status, alert_payload)`, `timeline_event(incident_id,
  to_status, created_at)`, `postmortem(incident_id)`
- [x] 3.4 Add a minimal LLM client factory stub and MCP client wrapper stub -
  not real calls, just the shape other modules import against (design.md
  Non-Goals)
- [x] 3.5 Add a Postgres service to `docker-compose.yml` at the repo root -
  the one file this change touches outside `modules/*` (design.md Decisions)

## 4. `orchestrator`: the LangGraph StateGraph

- [x] 4.1 Implement the `StateGraph` with a node for each of the five
  sub-agents (Investigator, Mitigation, Code-Fix, Communicator, Postmortem)
  and the tier-gate node (spec §7.1, §12.1)
- [x] 4.2 Wire every conditional edge from spec §10's FSM diagram, including
  the `fixing` and `escalated` branches, even though only the happy path is
  exercised by this change (design.md Non-Goals - graph shape is complete,
  those paths just aren't driven yet)
- [x] 4.3 Configure LangGraph's Postgres checkpointing against `argus_core`'s
  schema (spec §7.1)
- [x] 4.4 Implement the tier-gate node as a no-op pass-through (spec §13,
  stubbed per design.md Non-Goals)
- [x] 4.5 Implement the Orchestrator's entrypoint: accepts an `Alert` domain
  object (not raw JSON), creates the `Incident` row, and invokes the graph -
  called by `argus_web` (spec §7.1, §7.9)
- [x] 4.6 Implement the single-writer rule: every `Incident.status`/
  `HYPOTHESIS`/`ACTION` mutation is paired with a `TimelineEvent` row in the
  same transaction (spec §7.1, §11.1) - including the initial transition into
  `investigating` on incident creation, since the e2e test expects a
  `timeline_event` row for it (spec §10's `[*] --> investigating` edge)

## 5. Stub sub-agent nodes

- [x] 5.1 Investigator stub: returns a fixed hypothesis at confidence >= 0.75
  (spec §10 threshold), no ReAct loop, no tool calls
- [x] 5.2 Mitigation stub: no-op action, always reports the hypothesis
  `confirmed`
- [x] 5.3 Code-Fix stub: exists as a real node, not called by this change's
  happy path
- [x] 5.4 Communicator stub: exists as a real node, not called by this
  change's happy path
- [x] 5.5 Postmortem stub: on transition into `resolved`, writes a stub
  `POSTMORTEM` row with placeholder content

## 6. `argus_web`: the HTTP boundary and Grafana adapter

- [x] 6.1 Implement a deterministic Grafana-unified-alerting parser:
  `parse_grafana_alert(raw_json: dict) -> Alert` - plain field mapping, no
  LLM call (design.md Non-Goals; spec §7.9/§25 tracks generic/LLM-based
  ingestion as separate future work)
- [x] 6.2 Implement `POST /webhooks/alerts`: validates the incoming payload,
  runs it through the Grafana parser to build an `Alert`, calls the
  Orchestrator's entrypoint in-process with that `Alert` - never the raw
  payload - and returns `202` with `{"incident_id": ...}` (spec §7.9)
- [x] 6.3 Confirm `argus_web` holds no incident-domain logic of its own -
  parsing/validation and response shaping only (spec §7.9, Design Principle
  7, §4)

## 7. Verification

- [x] 7.1 Run `uv run nox -s lint` and `uv run nox -s typecheck` (mypy
  --strict) - both clean
- [x] 7.2 Run `uv run nox -s guard_e2e_boundary` - confirms no module's own
  `tests/` carries an `e2e` marker
- [x] 7.3 Run `tests/e2e/test_incident_lifecycle.py` via `uv run nox -s e2e`
  and confirm it passes (green)
- [x] 7.4 Confirm `uv run nox -s test_module -- <name>` passes cleanly for
  each of the eight new modules - unblocked: human-authored unit tests now
  exist in every `modules/*/tests/` directory (real tests for modules with
  input-dependent behavior - `agent_investigator`, `argus_core`, `argus_web`,
  `orchestrator`; placeholder scaffolding tests for pure stubs whose output
  doesn't depend on input - `agent_codefix`, `agent_communicator`,
  `agent_mitigation`, `agent_postmortem`). All eight pass.
