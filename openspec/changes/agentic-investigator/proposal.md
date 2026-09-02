## Why

The Investigator is described as an agent but does not behave like one. `investigate()`
decides everything that matters - which channels to read, over which windows, in which
order, and how many times - and the model is consulted once per iteration as a pure
function from a fixed `Evidence` bundle to a list of hypotheses. The retrieval plan is a
schedule computed from configuration before the model has seen a single log line, so it
cannot react to what it reads: an incident whose cause is plainly a change event two
minutes before the onset pays for the same three widening log reads as one where the
logs are the only evidence there is.

That is the wrong division of labour. Which minute an incident started is a measurement
and must stay in code. Which channel to pull next, and when there is enough to answer,
is a judgement - the thing the model is actually good at, and the thing it is currently
forbidden from doing.

## What Changes

- **BREAKING** `investigate()` becomes a `tool_use` loop. The alert and the located
  onset open the conversation; the model drives from there.
- The read tier's three retrieval calls become real tool definitions offered to the
  model - `get_metrics`, `get_logs`, `get_changes` - each taking its own window. The
  model chooses which to call, with what window, and how often.
- The model terminates by calling a `final_answer` tool carrying the ranked hypotheses,
  so the output stays typed and a stopped loop is distinguishable from a model that
  merely stopped talking.
- **BREAKING** The widening schedule is removed. `agent_investigator.widening` and the
  `investigation_max_iterations` lookback ladder go with it.
- A **budget** replaces the schedule as the loop's bound: a maximum number of tool
  calls, a maximum token spend, and a maximum wall-clock, all enforced by the loop and
  none of them visible to the model as something it can extend. A budget exhausted
  without a `final_answer` is the new "insufficient evidence" outcome.
- Onset detection stays exactly as it is - deterministic, computed from the metrics
  summary before the loop opens - and is stated to the model as a fact rather than
  offered as a question. The loop therefore still retrieves metrics once itself, before
  the model's first turn.
- The `Evidence` bundle stops being the unit the model is asked about. What it saw is
  reconstructed from the transcript instead, which is also what makes the run auditable.
- Testing moves in three directions: the loop is tested against a **scripted stub model**
  that returns tool calls chosen by the test, so every budget and termination rule is
  deterministic and needs no recording; the model's judgement moves to the **eval** suite
  as a pass rate; and `e2e_replay` keeps proving the wiring on one recorded path.

## Capabilities

### New Capabilities
- `investigator-tool-loop`: the `tool_use` conversation itself - the tool definitions
  offered, the opening message, `final_answer` as the only typed exit, and how the
  transcript is turned into `Findings`.
- `investigation-budget`: the bounds the loop enforces on the model - tool calls, tokens,
  wall-clock - what happens at each limit, and the requirement that metrics are read at
  least once regardless of what the model asks for.

### Modified Capabilities
- `investigator-react-loop`: the fixed-iteration structure, the widening schedule, and
  the derived-lookback requirements are removed. What survives is onset detection, the
  baseline/persistence rules, and the "insufficient evidence" outcome - now reached by a
  spent budget rather than a spent schedule.
- `investigation-rounds`: a resumed round no longer resumes a schedule position. What a
  second round carries forward is the refuted attempts, which was always the more
  valuable half.
- `investigator-cause-detection`: retrieval is no longer performed on the model's behalf
  before it is asked; the same read-tier tools are now called by the model itself.

## Impact

- `two-phase-retrieval` is deliberately *not* modified: it specifies the read-tier
  server's own tools, windows and clamping, all of which stand unchanged. What changes is
  only who calls them.
- `modules/agent_investigator/` - `__init__.py` rewritten around the loop;
  `widening.py` deleted; `retrieval.py` re-shaped into tool definitions rather than
  fetch functions; `reasoning.py`'s single-shot `propose_hypotheses` seam replaced by a
  conversational one.
- `modules/argus_core/llm.py` - needs a `tool_use` turn-taking API, not just
  "evidence in, hypotheses out". This is the largest single piece of work.
- `modules/argus_core/config.py` - `investigation_max_iterations`,
  `log_initial_lookback_minutes` and `log_max_window_minutes` lose their scheduling role;
  new budget settings replace them.
- `modules/argus_core/events.py` - the narration becomes per tool call rather than per
  iteration, which is also the natural place for `REPLAY_LOG` (spec §4 principle 6) to
  finally land.
- `modules/orchestrator/` - the investigating node's contract is unchanged; it still
  receives `Findings`.
- `modules/anthropic_double/` - must replay multi-turn `tool_use` exchanges, not single
  completions. Recordings become path-dependent.
- `docs/spec-and-architecture.md` §9, §10, §16.
- Existing `agent_investigator` tests that pin the schedule are removed; new loop tests
  are proposed in chat under the TDD policy.
