## Why

The Investigator is a single deterministic pass: it fetches the whole log with
one bare `get_log_lines()` call, keyword-matches for a feature flag toggle, and
returns a hardcoded `STUB_CONFIDENCE = 0.9` whether or not it found anything.
Every retrieval tool §16 describes now exists and is correct, but nothing
drives them - and the fixed confidence means "Argus could not determine the
cause" is currently inexpressible, which blocks §9's escalation path and the
"knows its limits" success criterion (§3) outright.

This change makes the `investigating` phase the ReAct loop §9 specifies, and
puts a real LLM behind the hypothesis for the first time.

## What Changes

- **The `investigating` node becomes an iterative loop** rather than one pass:
  query metrics → locate onset → read an onset-anchored log window → form a
  hypothesis → score it → widen or exit. Bounded by a configured iteration
  budget and the existing maximum window span.
- **`Hypothesis` becomes a real domain model in `argus_core`.** It is already a
  table (§11.1) and already crosses agent boundaries, but today
  `IncidentState.hypothesis` is a bare `str | None`. It gains a model beside
  `Alert` and `CauseType`, carrying summary, cause type, confidence, and the
  evidence relied on. **BREAKING** for every reader of
  `IncidentState.hypothesis`.
- **A real LLM forms the hypothesis.** `argus_core.llm.StubLLMClient` is
  replaced with an Anthropic-backed client on `claude-opus-5`. The hypothesis,
  the `cause_type`, and the confidence all come from the model against
  retrieved evidence, rather than from keyword matching. **BREAKING** for
  `LLMClient`: `complete(prompt) -> str` is insufficient for a typed,
  confidence-bearing verdict and is replaced (see design.md).
- **Widening triggers structurally, not on self-reported confidence** (§9): if
  the earliest bucket in the window is already anomalous, onset predates the
  window, so the next iteration reaches further back. Low confidence is a
  secondary trigger; a model that formed a hypothesis from too little evidence
  reports high confidence and would never widen on its own.
- **Exhaustion becomes a real outcome.** When the iteration budget or the
  maximum span runs out with no hypothesis clearing the threshold, the loop
  exits to `escalated` carrying "insufficient evidence" - never a fabricated
  hypothesis. **BREAKING**: `investigate()` may now return no cause and a
  confidence below `mitigate_threshold`, which callers must handle.
- **A test double for the Anthropic API.** A server speaking the Messages API,
  which the SDK reaches by `base_url` - so the seam sits *below* the SDK and
  our adapter, the SDK's serialization, and our schema are all genuinely
  exercised. It replays responses recorded from the real API, and a control
  endpoint seeds what comes next: a given hypothesis, a refusal, a 429, or a
  response that violates the schema. Testing what Argus does when the model
  returns garbage is impossible today and becomes a two-line test.
- **A new `eval` pytest marker** for benchmark tests (§21): real API, fixed
  evidence, asserting the model picked the right `cause_type`. These test the
  *prompt*, cost money, and do not run on every commit.
- **`STUB_CONFIDENCE` is deleted**, along with the two tests that assert
  against it.
- **Config gains** the iteration budget and the anomaly threshold the
  structural widening trigger reads off the metrics summary.

Not in this change: the Chroma similar-incidents lookup that seeds §9's first
hypothesis (step B) - it needs the long-term memory store, which does not
exist yet. The loop is built with that step absent, not designed against its
absence.

## Capabilities

### New Capabilities
- `investigator-react-loop`: the bounded iterative investigation loop -
  onset-anchored retrieval per iteration, structural widening, an iteration
  budget, and exhaustion to `escalated` with insufficient evidence rather than
  a manufactured hypothesis.
- `llm-hypothesis-generation`: a real Claude-backed client behind a typed
  seam, returning a hypothesis, a cause type, and a calibrated confidence
  against retrieved evidence - replacing keyword matching and the fixed stub
  confidence.
- `anthropic-test-double`: a programmable stand-in for the Anthropic API that
  the SDK is pointed at by `base_url`, replaying recorded real responses, so
  every tier below e2e exercises the real adapter and the real SDK without
  spending tokens or depending on a live service - plus the contract tests
  that keep the double honest.

### Modified Capabilities
- `investigator-cause-detection`: cause determination stops being
  deterministic keyword matching over an unwindowed log and becomes an LLM
  verdict over an onset-anchored window; "no recognizable cause" stops being
  a fallback that still reports high confidence.
- `incident-lifecycle`: `investigating → escalated` gains its real trigger -
  exhausted iterations or exhausted window span - rather than being reachable
  only via a confidence value the code never actually produced.

## Impact

- Modified: `modules/agent_investigator/` (the loop itself),
  `modules/argus_core/src/argus_core/llm.py` (real client, typed verdict),
  `modules/argus_core/src/argus_core/config.py` (iteration budget, anomaly
  threshold), `modules/orchestrator/` (the investigating node must tolerate an
  undetermined outcome).
- New runtime dependency: the `anthropic` SDK, and an `ANTHROPIC_API_KEY` in
  configuration - the first secret the system actually requires (§14).
- Tests: `modules/agent_investigator/tests/test_investigate.py` loses its two
  tautological `STUB_CONFIDENCE` assertions. The LLM is injected as a test
  double, so unit tests stay deterministic and offline; only a
  deliberately-marked test may reach the real API.
- `tests/e2e/test_scenario_investigation.py` currently asserts a
  `feature-flag-toggle` diagnosis produced by keyword matching. With a real
  model the assertion has to tolerate non-determinism in the hypothesis text
  while still pinning `cause_type`.
- The `bad-deployment` scenario stays unevaluated: only `feature-flag-toggle`
  is exercised, deliberately. Nothing in the loop special-cases either.
