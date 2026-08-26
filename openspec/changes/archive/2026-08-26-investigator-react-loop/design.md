## Context

`investigate()` today is one pass: `get_log_lines()` with no window, a keyword
scan for a flag toggle, and `STUB_CONFIDENCE = 0.9` returned regardless of what
was found. The retrieval side is finished and correct - `get_metrics_summary`
locates onset, `get_log_lines` takes an onset-anchored window, and both clamp
at a configured maximum span - but no caller drives them.

Two things have to arrive together for that to change. The loop needs a
*verdict* to iterate on, which keyword matching cannot produce (it has no
notion of confidence, only of match/no-match), and it needs somewhere honest to
put "I don't know", which the fixed confidence forecloses. So this change
introduces the real LLM and the loop in one step.

Constraints in play: `argus_core.llm` currently exposes `complete(prompt) ->
str` backed by a `StubLLMClient` that raises; §9 fixes the loop's first two
steps and its widening rule; §10 fixes the escalation trigger at 3 failed
iterations and the mitigate threshold at 0.75; §13 keeps the Investigator
read-only, so nothing here can touch a write path.

## Goals / Non-Goals

**Goals:**
- The `investigating` phase is a bounded iterative loop, not a single pass.
- A real Claude call produces the hypothesis, the cause type, and the
  confidence, against evidence the loop retrieved.
- "Argus could not determine the cause" is expressible, distinguishable from a
  confident answer, and cannot be reported with high confidence.
- Widening is decided structurally, off the metrics summary - never off the
  model's self-assessment alone.
- Unit tests remain deterministic and offline.

**Non-Goals:**
- Chroma similar-incidents seeding (§9 step B). No long-term memory store
  exists; the loop is built with the step absent.
- `CauseType.BAD_DEPLOYMENT` detection or evaluation. One scenario only.
- The change-event retrieval channel for causes that precede onset by an
  unbounded lag - deliberately deferred; see Risks.
- `REPLAY_LOG` capture of the LLM call (§4 principle 6). Called out in Risks.
- Prompt-quality tuning against a benchmark suite (§21). This change makes the
  call; it does not optimize it.

## Decisions

### 1. `Hypothesis` is a core domain model, not an LLM response type

A hypothesis is not something the LLM invented - it is an Argus domain object
that predates this change. It is already a table (§11.1), and it already
crosses agent boundaries: the Investigator writes it, Mitigation reads it to
confirm or refute, Postmortem quotes it. Today that is papered over -
`IncidentState.hypothesis` is a bare `str | None`, and the `hypothesis` table
has no model behind it - which is the same flattening this change is undoing
on the confidence side.

So it lands in `argus_core/models/hypothesis.py`, beside `Alert`, `CauseType`,
`MetricBucket`, and `IncidentState`:

```python
class Hypothesis(BaseModel):
    id: UuidStr = Field(default_factory=lambda: str(uuid4()))
    incident_id: UuidStr
    summary: str                    # was `description` in the table
    cause_type: CauseType | None
    confidence: float | None        # None when no cause was determined
    supporting_evidence: list[str]  # the log lines it actually relied on - new column
    tested: bool = False
    result: str | None = None
```

`IncidentState.hypothesis` changes from `str | None` to `Hypothesis | None`.

**There is exactly one `Hypothesis`.** `orchestrator/repository/hypotheses.py`
currently declares its own, and the duplicate is the mistake: a row in the
`hypothesis` table *is* a hypothesis written down, not a different concept. The
repository keeps `record()` and `get_latest_by_incident()` and imports this
model; `UuidStr` moves from `orchestrator/repository/_types.py` into
`argus_core` with it, since a domain model cannot reach into another package's
private module.

**Identity is generated at construction, not by the database.** An entity has
identity by definition; a `Hypothesis` that is not yet itself until it has been
somewhere else is not an entity. A `default_factory` id means no nullable
`id`, no "is this saved yet?" branch in any reader, references and logging
before persistence, and idempotent inserts. The two usual alternatives - a
nullable id until save, or a separate `NewHypothesis` type - both exist only to
work around the database owning identity.

`created_at` stays out of the model: it is an audit fact the table records, and
nothing in the domain reads it.

*Naming considered and rejected:* having the Investigator return a `Decision`
or `Conclusion` that the Orchestrator then stores as a `Hypothesis`. Both words
mean *settled*, and a hypothesis is deliberately the opposite - a guess put up
to be tested, which is why Mitigation answers it with confirmed/refuted (§7.3).
An Orchestrator whose job is to rename one type into an identically-shaped
other is the smell that says they were one type. `HypothesisRow` was rejected
too: naming a class after the pattern it implements leaks technical vocabulary
into the domain language, and nobody says "the hypothesis row".

The one thing that *does* deserve a separate name is what the model literally
returned, before it is a domain object - flat, nullable, shaped by the API
rather than by us. That stays private to the adapter (`_LlmVerdict`) and never
escapes it.

*Alternative considered:* define it inside `agent_investigator` and let other
agents import it. Rejected - it violates the module-boundary rule, and it puts
a shared concept behind one agent's door.

### 2. `LLMClient` returns that model, not a string

`complete(prompt) -> str` is replaced by a domain-shaped method:

```python
class LLMClient(Protocol):
    def propose_hypothesis(self, evidence: Evidence) -> Hypothesis: ...
```

The adapter uses structured outputs (`output_config.format`) with
`client.messages.parse()`, so the schema is enforced at the API boundary
rather than by a hand-written parser coping with a model that prepended prose.

*Alternative considered:* keep `complete(prompt) -> str` and parse in the
Investigator. Rejected - it puts response-format handling in the agent, and
every agent added later reinvents it. A generic `complete` is also the wrong
seam for testing: a stub returning a string forces every test to encode the
model's serialization format, where a stub returning a `Hypothesis` encodes
only the decision.

*Trade-off:* the Protocol now carries one investigation-specific method, and
will accumulate one per agent as Postmortem and Mitigation need their own.
That is about the *interface*, not the model - and the fix when it gets
crowded is one small client per agent over a shared transport, the same shape
as the MCP server split (§12.1). Not worth pre-building for a single caller.

### 3. The model is `claude-opus-5`, adaptive thinking, effort `high`

Root-cause reasoning over noisy evidence is exactly the "hard to fully specify
in advance" case that justifies a capable model. Adaptive thinking is on by
default for this model. `effort: "high"` is the default and is right here;
`max_tokens` at 16000, non-streaming, since a hypothesis is short and the
request is not long-running.

*Alternative considered:* Haiku for cost, since the loop may run 3 times per
incident. Rejected - §17 assigns model choice per task, and the accuracy
targets in §3 (≥70% root cause) are the whole point of the project. Cost
control belongs in the iteration budget, not in a weaker model.

### 4. A confident verdict that names nothing is unconstructible

`cause_type: None` at confidence 0.9 - "I found nothing, and I'm sure" - is
exactly the bug `STUB_CONFIDENCE` had. Rather than produce that object and
correct it afterwards, a validator makes it impossible to build: a cause and a
confidence arrive together, or neither does.

```python
    @model_validator(mode="after")
    def _a_cause_and_a_confidence_come_together(self) -> Hypothesis:
        if (self.cause_type is None) != (self.confidence is None):
            raise ValueError(
                "a hypothesis has both a cause and a confidence, or neither"
            )
        return self

    def is_confident_enough(self, threshold: float) -> bool:
        """Whether this hypothesis is confident enough to act on (spec §10).

        An undetermined hypothesis never is - there is no cause to act on,
        which is the honest answer rather than a low score.
        """
        return self.confidence is not None and self.confidence >= threshold
```

`is_confident_enough` exists so no caller hand-rolls
`confidence is not None and confidence >= threshold`. Control flow asks the
question it actually has; `confidence` remains on the model for persistence and
for the postmortem to report.

The threshold is a parameter, not read from `Settings` inside the model - a
hypothesis is a domain entity and has no business knowing how Argus is
configured. This costs callers nothing: the only current one,
`orchestrator/graph.py`, already reads `get_settings().mitigate_threshold` into
a local, and the investigator loop reads `Settings` regardless.

The model still answers in a flat shape, because that is what structured
outputs do well; the adapter is the single place that knows both, and
constructing the `Hypothesis` is where the invariant gets enforced.

*Alternative considered:* clamping the confidence when `cause_type` is `None`.
Rejected - a clamp is a rule you have to remember, and nothing stops a second
code path from forgetting it. *Also considered:* a `Determined | Undetermined`
union, which is stronger still, and a `CauseType.UNDETERMINED` sentinel, which
would make the enum stop being a list of causes. The validator gets the safety
without either cost.

### 5. Onset is where the metric leaves its own baseline

The alert is one moment in time; it says nothing about the 360 minutes around
it. To anchor a log window the loop has to answer "which minute did this
start?", and that is a question about the shape of the metric, not about the
alert.

```
1%  1%  1%  1%  1%  1%  2%  4%  9%  18%  30%
                            ↑              ↑
                        onset           alert fires
```

So: the calm stretch of the window is the baseline. A minute counts as the
incident once it sits further from that baseline than the baseline's own
wobble - `anomaly_deviations_from_baseline`, defaulting to 3. Onset is the
earliest such minute. Both the error rate and the p95 latency are checked this
way, since the two fixture scenarios move different ones.

Measuring in the baseline's own spread, rather than in error-rate points, is
what makes one setting work everywhere: a service that idles at 0.5% errors
and one that idles at 8% are both judged against themselves.

The widening trigger falls out of the same thing. If the *earliest* minute in
the window is already elevated, there is no calm stretch on screen - the
baseline is off the left edge, so the incident began before anything retrieved
and the next iteration has to reach further back.

*Alternative considered, and initially written:* two absolute thresholds in
config - error rate over 10%, p95 over 800ms. Rejected. It would call the 2%
minute above healthy and start reading logs at 18%, by which point the cause
has scrolled off; the numbers would be wrong for any service whose normal
differs from the fixture's; and they duplicate a decision the operator already
made in their own alerting tool. The architecture doc (§16) had said "the
first minute whose values break from baseline" all along - this decision was
the deviation, not the correction.

*Alternative considered:* let the model decide which minutes are anomalous.
Rejected - it makes the widening trigger non-reproducible across benchmark
runs, and re-introduces the failure §9 designs against, where the loop's
control flow depends on the model's own sense of whether it has seen enough.

*Known limit:* a slow ramp has no crisp first minute, so onset lands wherever
the noise band ends. No detection method fixes that. It argues for erring
early - a slightly-too-wide log window costs tokens, a slightly-too-late one
misses the cause entirely.

### 6. The widening schedule is computed up front, not stepped into

The lookback for every iteration is derived once, from the three numbers that
constrain it - the initial lookback, the maximum span, and the iteration budget
- as a geometric progression from the first to the last:

```python
def widening_schedule(initial_minutes: int,
                      maximum_minutes: int,
                      iterations: int) -> list[int]:
    """The lookback each iteration uses, ending exactly at the maximum."""
```

With the defaults (30, 180, 3) that is **30, 73, 180**.

Two responsibilities stay separate: the *structural trigger* (decision 5)
decides **whether** to take another step - the earliest bucket in the window is
anomalous, so onset predates it - and the schedule decides **how far** that
step reaches. Low confidence with iterations remaining is a secondary trigger.

*Alternative considered, and initially chosen:* double the lookback each
iteration, clamped at the maximum. Rejected once the arithmetic was checked -
30, 60, 120 under the default budget never reaches the 180 ceiling, so the
"onset predates the maximum span" exhaustion condition was unreachable and the
last iteration left a third of its allowance unspent. A precomputed schedule
cannot drift that way: it ends at the maximum *by definition*, and it stays
coherent when the budget or the ceiling is reconfigured, where the doubling
rule silently needs someone to re-check where it lands.

Geometric rather than linear (which would give 30, 105, 180) because causes
cluster near the onset: small steps first, the long reach last.

The loop exits to `escalated` with no cause when the iteration budget is spent,
which - since the last iteration is the maximum span - also means the window
reached everything it was permitted to read. That is the honest outcome: the
incident began before anything Argus can see, which is a real answer and not a
failure to try.

### 7. The LLM is injected at the call, like every other collaborator

`investigate(alert, llm=get_llm_client(), ...)` - a default-argument seam, per
the repo's mocking conventions. Tests of the *loop* pass a
`create_autospec(LLMClient)` and never reach an HTTP call at all: they are
about what the loop does with a verdict, not about how the verdict was
obtained.

### 8. The Anthropic API gets a test double, below the SDK

A `create_autospec(LLMClient)` proves nothing about the adapter itself - the
prompt, the schema, the parsing, the error handling. That code is the riskiest
thing in this change and would otherwise be exercised for the first time in
production.

So the adapter gets tested against a **server that speaks the Messages API**,
selected with the SDK's own `base_url`. The seam is below the SDK, which means
the real adapter, the real `messages.parse`, the real schema transform and the
real response parsing all run - everything except Anthropic.

**The double replays recordings, it does not invent answers.** A real call is
made once and its raw response saved; the double serves that back. A control
endpoint (`/double-control/*`, the same shape as the Target Service's scenario
control) seeds what comes next - a particular hypothesis, a refusal, a 429, a
response that violates the schema. That last case is untestable today.

**Four tiers, four questions:**

| Tier | Runs against | Answers |
|---|---|---|
| `unit` | nothing | is the pure logic right - baseline, onset, schedule, validator |
| `integration` | the double | given *this* verdict, does Argus do the right thing |
| `contract` | double **and** the real API | is the double still a faithful stand-in |
| `eval` (new marker) | the real API | did the model pick the right `cause_type` for this evidence |
| `e2e` | the real API | does the whole system work end to end |

**What the contract test can and cannot compare.** Not content - the model
writes different prose every call. It compares *structure*: both return
something that parses into a `Hypothesis`, both reject the same malformed
request the same way, both carry the same `stop_reason` vocabulary. That is
enough to catch what actually breaks - a renamed field, a changed error shape,
a new required parameter. When a recording goes stale against the live API,
the contract test is what says so.

**"Did it find the right cause" is not a contract question.** It is answered
by the `eval` tier against the real model with known evidence, and by e2e with
a seeded scenario. Both are possible only because `cause_type` is a `CauseType`
enum rather than prose - a fixed, small set the model either picked correctly
or did not. This is the payoff of decision 2 that was not obvious when it was
made.

*Alternative considered:* record/replay inside the SDK via a transport mock.
Rejected - it tests less (the HTTP layer is skipped) and couples the tests to
SDK internals that are not part of its public contract. A server on a port is
both more honest and more stable.

## Risks / Trade-offs

- **The model self-reports confidence, and models are overconfident.** →
  Confidence never drives widening (decision 5), and a confident no-cause
  verdict being unconstructible (decision 4) removes the worst failure mode. Calibration itself is a §21
  benchmark concern, not solvable here.
- **The cause can precede onset by more than the maximum window.** → Not
  solved. A flag toggled an hour before any request traverses that path is
  invisible to any log window Argus is permitted to read. The loop reports
  insufficient evidence rather than guessing, which is correct but not
  satisfying; the separate change-event channel is the real fix and is
  deferred.
- **e2e tests become non-deterministic.** → Assert on `cause_type` and on the
  incident reaching `mitigating`, never on hypothesis wording. Accept that a
  model change can turn the suite red for a real reason.
- **The LLM call is not captured in `REPLAY_LOG`,** violating §4 principle 6
  the moment a real call is made. → Accepted knowingly for this change; every
  benchmark run will re-spend tokens until replay lands. Flagged as the next
  change after this one.
- **First hard dependency on a secret.** `ANTHROPIC_API_KEY` reaches the
  process via environment/`Settings`, not Vault (§14) - Vault is not built.
  → Keep it out of the repo and out of logs; move to Vault with the other
  credentials when `argus-write-mcp` forces the issue.
- **Cost per incident becomes non-zero and unbounded by anything but the
  iteration budget.** → The budget is the control. Worth watching once the
  benchmark suite runs many scenarios per CI run.
