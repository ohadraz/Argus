Tests are human-owned (`AGENTS.md`): every task below that needs a test means
*propose it in chat, confirm it is red, then implement*. Tasks marked
**(test)** are proposal tasks, not implementation ones.

## 1. Config and dependencies

- [x] 1.1 Add the `anthropic` SDK as a runtime dependency of `argus_core`, and `uv sync --all-packages`
- [x] 1.2 Add `anthropic_api_key`, `investigation_max_iterations` (default 3), and `anomaly_deviations_from_baseline` (default 3.0) to `Settings`
- [x] 1.3 **(test)** Propose `test_config.py` cases: an iteration budget below 2 is rejected (one iteration cannot widen), exactly 2 is accepted, and a non-positive deviation count is rejected
- [x] 1.4 Add the single-field constraints to `Field` (`ge=2`, `gt=0.0`); the `model_validator` stays for cross-field invariants only
- [x] 1.5 Document the required `ANTHROPIC_API_KEY` in `.env.example`, whitelisted past the blanket `.*` rule in `.gitignore`

## 2. The typed LLM seam

- [ ] 2.1 **(test)** Propose tests for `Hypothesis`: a cause without a confidence is rejected, a confidence without a cause is rejected, and `is_confident_enough` is false for an undetermined hypothesis at any threshold
- [x] 2.2 Add `argus_core/models/hypothesis.py` - the `Hypothesis` domain model with its validator and `is_confident_enough(threshold)` - beside `alert.py` and `cause.py`, plus an `Evidence` input model
- [x] 2.2a Move `UuidStr` from `orchestrator/repository/_types.py` to `argus_core` - the domain model needs it and cannot import another package's private module
- [x] 2.2b Give `Hypothesis` the entity fields: `id` (`default_factory`, never null), `incident_id`, `tested`, `result`
- [x] 2.2c **(test)** Propose the test that two hypotheses built the same way still have different ids - identity comes from construction, not from the database
- [x] 2.2d Delete `orchestrator/repository/hypotheses.Hypothesis`; `record()` and `get_latest_by_incident()` take and return the `argus_core` one
- [x] 2.2e Migrate the `hypothesis` table: rename `description` to `summary`, add a `supporting_evidence` column
- [x] 2.3 Change `IncidentState.hypothesis` from `str | None` to `Hypothesis | None`, and update every reader
- [x] 2.3a **(test)** Propose the `test_graph.py` changes - it builds hypotheses as bare strings throughout - and the e2e assertion updates
- [x] 2.3b `investigate()` returns a `Hypothesis` and takes `incident_id`; the no-cause branch returns cause `None` *and* confidence `None` rather than a fabricated hypothesis
- [x] 2.3c Make the Communicator stub work rather than raise - escalation reaches it now, and a stub that raises on a live path turns "I don't know" into a crash
- [x] 2.3d `nox -s e2e` tears down with `-v`: the Postgres volume outlived the run, and `CREATE TABLE IF NOT EXISTS` never alters an existing table, so schema changes silently did not land
- [ ] 2.4 Replace the `LLMClient` Protocol's `complete(prompt) -> str` with `propose_hypothesis(evidence) -> Hypothesis`
- [ ] 2.5 Implement the Anthropic-backed adapter: `claude-opus-5`, adaptive thinking, `effort: "high"`, `max_tokens: 16000`, structured outputs via `messages.parse()`
- [ ] 2.6 Map the model's flat response onto `Hypothesis` in the adapter - the one place the wire shape and the domain shape meet
- [ ] 2.7 Replace `graph.py`'s inline `confidence >= mitigate_threshold` with `hypothesis.is_confident_enough(mitigate_threshold)`
- [ ] 2.8 Delete `StubLLMClient`; make `get_llm_client()` return the real adapter
- [ ] 2.9 Write the hypothesis prompt: the alert, the metric buckets, the log window, and an explicit instruction that "cause undetermined" is a valid and expected answer

Verified against the live API before any of the above: `output_format=<pydantic
type>`, `output_config={"effort": "high"}`, `thinking={"type": "adaptive"}` on
`claude-opus-5`. Passing the type inside `output_config={"format": ...}` raises
`TypeError: Object of type ModelMetaclass is not JSON serializable`.

## 2b. The Anthropic test double

- [ ] 2b.1 Add `anthropic_base_url` to `Settings` (empty = the real API) and pass it to the client constructor - the only thing that selects the double
- [ ] 2b.2 Scaffold `modules/anthropic_double/` per the `new-module` skill; add it to `EXCLUDED_FROM_TESTS` in `noxfile.py` if it carries no suite of its own
- [ ] 2b.3 Implement `POST /v1/messages` returning a real `Message` shape - `id`, `type`, `role`, `model`, `content`, `stop_reason`, `usage`
- [ ] 2b.4 Implement the control route (`/double-control/*`): seed the next response - a chosen hypothesis, a refusal, a 429, a 500, or a schema-violating body
- [ ] 2b.5 Record real responses to files, and serve them back; store the recordings in the repo so a fresh clone needs no key to run integration tests
- [ ] 2b.6 Add the `eval` marker to the root `pyproject.toml` marker list (CLAUDE.md forbids adding one without updating that list)
- [ ] 2b.7 Bring the double up in `noxfile.py`'s `e2e`/integration wiring the way `read_mcp_server` already is
- [ ] 2b.8 **(test)** Propose the integration tests: the real adapter against the double for a seeded hypothesis, a seeded refusal, a seeded 429, and a seeded schema violation
- [ ] 2b.9 **(test)** Propose `tests/contract/test_anthropic_double.py`: the same request to both the double and the real API produces a parseable hypothesis, and an equivalent malformed request produces an equivalent error
- [ ] 2b.10 **(test)** Propose the `eval` tests: fixed flag-toggle evidence yields `CauseType.FEATURE_FLAG_TOGGLE`; evidence with no change event yields no determined cause
- [ ] 2b.11 Confirm the contract tests fail loudly when a recording is stale, by hand-editing one recording
- [ ] 2b.12 **BEFORE COMMITTING**: lock `modules/anthropic_double/` against Claude in `.claude/hooks/block_test_writes.py`, alongside `argus_testkit` - a rigged double could make every integration test pass. Claude writes it first, then the door closes.

## 3. Deterministic anomaly detection

- [ ] 3.1 **(test)** Propose tests for baseline classification: a departure from a steady rate is anomalous and the steady minutes are not; the same shape is caught at a low and a high steady rate; a p95 departure at a steady error rate is caught; a window with no calm stretch reports its earliest bucket as anomalous
- [ ] 3.2 Implement the baseline and its spread over a window's buckets, robust to the incident's own minutes skewing it
- [ ] 3.3 Implement `find_onset(buckets)` - the earliest bucket departing from that baseline - in a public module of `agent_investigator` (not a `_name`; the loop's tests need it)
- [ ] 3.4 Implement `earliest_bucket_is_anomalous(buckets)`, the structural widening trigger - it means "no calm stretch is visible in this window"

## 4. The ReAct loop

- [ ] 4.1 **(test)** Propose tests for `widening_schedule(initial, maximum, iterations)`: starts at the initial lookback, ends exactly at the maximum, strictly increases, and one entry per iteration
- [ ] 4.2 Implement `widening_schedule` as a pure function - geometric from the initial lookback to the maximum span
- [ ] 4.3 **(test)** Propose the loop tests: confident first iteration exits immediately; the iteration budget is never exceeded; an anomalous earliest bucket advances to the next scheduled lookback; a spent budget returns an undetermined hypothesis
- [ ] 4.4 Implement the loop body: metrics summary → onset → onset-anchored `get_log_lines` → `propose_hypothesis`
- [ ] 4.5 Implement the exit conditions - confident enough, or the schedule exhausted with the earliest bucket still anomalous
- [ ] 4.6 Rewrite `investigate()` around the loop; inject `llm` and the retrieval calls as default-argument seams
- [ ] 4.7 Delete `STUB_CONFIDENCE` and `_determine_cause`
- [ ] 4.8 **(test)** Propose deleting the two tautological `STUB_CONFIDENCE` tests from `test_investigate.py`

## 5. Orchestrator and persistence

- [ ] 5.1 **(test)** Propose a `test_graph.py` case: an undetermined cause routes to `escalated` and records insufficient evidence
- [ ] 5.2 Make the investigating node tolerate an undetermined outcome without treating it as an error
- [ ] 5.3 Persist `supporting_evidence` alongside `description`, `confidence`, and `cause_type` on the hypothesis row (schema migration if needed)
- [ ] 5.4 Record "insufficient evidence" on the `TimelineEvent` for an exhaustion-driven escalation

## 6. End-to-end and verification

- [ ] 6.1 **(test)** Propose reworking `tests/e2e/test_scenario_investigation.py` to assert on `cause_type` and final status only, never on hypothesis wording
- [ ] 6.2 **(test)** Propose the no-scenario e2e case: escalates rather than resolving (this inverts the current `test_incident_lifecycle.py` expectation)
- [ ] 6.3 e2e runs against the real API, so CI needs `ANTHROPIC_API_KEY` as a secret; integration runs against the double and needs none
- [ ] 6.4 `uv run python -m nox -s lint`, `typecheck`, `test_all`, `guard_e2e_boundary` all green
- [ ] 6.5 `uv run python -m nox -s e2e` green
- [ ] 6.6 `uv run python -m nox -s contract` green - the first real inhabitant of `tests/contract/`
- [ ] 6.7 Update `docs/spec-and-architecture.md` §9 if the implemented loop diverges from the diagram

## 7. Follow-ups to raise, not to do here

- [ ] 7.1 Raise the `REPLAY_LOG` gap - the LLM call is uncaptured, violating §4 principle 6 - as the next change
- [ ] 7.2 Remind the user about the change-event retrieval channel (option C), still the real fix for a cause preceding onset by an unbounded lag
