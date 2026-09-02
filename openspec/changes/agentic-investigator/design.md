## Context

Today `investigate()` is a loop over a schedule. It reads metrics once, locates the
onset, reads changes once, then reads a log window per iteration and asks the model a
single question per iteration through `LLMClient.propose_hypotheses(evidence)`. The
model's answer influences only whether the loop stops; it never influences what is read
next. Every retrieval decision - channel, window, order, count - is made in code before
the model has seen anything.

The seam that makes this shape stick is `LLMClient`, which is deliberately
`propose_hypotheses(evidence) -> list[Hypothesis]` rather than `complete(prompt) -> str`.
That docstring's reasoning is sound and this change does not overturn it: the seam should
still be stated in Argus's terms and still be impossible to satisfy without producing a
verdict. What has to change is that a single call can no longer express the interaction,
because the model now needs to speak more than once.

Three constraints frame everything below. The onset is a measurement and must stay
reproducible. The read tier must stay incapable of writing - the tools offered to the
model come from `read_mcp_client` and nothing else. And `e2e_replay` must stay free and
keyless, which puts real pressure on `anthropic_double`.

## Goals / Non-Goals

**Goals:**

- The model decides which retrieval channel to pull, over which window, and when it has
  enough to answer.
- The loop's termination is enforced by code and cannot be talked past by the model.
- The output stays typed: an investigation still returns `Findings` carrying ranked
  `Hypothesis` values, and the orchestrator's investigating node does not change.
- A run is auditable from its transcript - what was asked for, what came back, in order.
- The loop is testable without a model and without a recording.

**Non-Goals:**

- Letting the model locate the onset, or contest the one it is given.
- Giving the Investigator any write-tier tool. It stays read-only, by possession of the
  read client rather than by instruction.
- Changing what a `Hypothesis` is, how candidates are ranked, or how the mitigate
  threshold is applied. Those specs stand.
- Making the model's *judgement* deterministic. It is not, and the testing strategy
  below is built around admitting that rather than papering over it.

## Decisions

### The onset is computed first and stated, not asked

The loop reads metrics itself, before the model's first turn, and runs `find_onset` on
the result exactly as today. The onset, and whether it is only a lower bound
(`earliest_bucket_is_anomalous`), go into the opening message as facts.

*Why:* the onset anchors every window and every later comparison. A sampled call that
locates it differently on a second run makes two investigations of the same incident
incomparable, and makes the eval suite measure noise. This also settles the "must
metrics be pulled at least once" question structurally - they are already pulled, by the
loop, before the model can choose otherwise. The model may still call `get_metrics`
again for a different window; it simply cannot skip the first read.

*Alternative rejected:* offer `find_onset` as a tool the model calls. It adds a turn to
buy nothing - the answer is the same every time and the loop needs it before it can even
write the opening message.

### `final_answer` is the only typed exit

The model is given a fourth tool alongside the three retrieval ones. Its input schema is
the ranked-hypotheses shape that `propose_hypotheses` returns today. The loop ends when
that tool is called, and `Findings` is built from its arguments.

*Why:* it keeps the "impossible to satisfy without producing a verdict" property of the
current seam. It also makes "the model stopped calling tools and wrote prose" a distinct,
detectable outcome rather than something to be parsed hopefully.

*Alternative rejected:* end on `stop_reason == "end_turn"` and parse the final text.
That is exactly the string-in/string-out seam the current `LLMClient` docstring rejects,
and it makes a wandering model indistinguishable from a finished one.

### The budget is enforced by the loop, in three independent dimensions

- **Tool calls** - the count that bounds retrieval breadth.
- **Tokens** - cumulative across the conversation, the one that bounds cost.
- **Wall-clock** - the one that bounds an incident's time-to-mitigate.

Each is checked by the loop between turns. Whichever binds first ends the investigation.
None is expressed to the model as something it can request more of.

*Why three:* they fail differently and none subsumes the others. A model that calls
`get_logs` on a three-hour window six times is cheap in calls and ruinous in tokens; one
that loops on a tiny window is cheap in tokens and burns the clock. Bounding only calls,
which is the tempting single knob, bounds the least expensive of the three.

*How exhaustion reports:* a spent budget with no `final_answer` yields the existing
"insufficient evidence" outcome - one candidate, no `cause_type`, no `confidence`, and a
summary naming which bound was hit. That last part is new and matters: "I ran out of
time" and "I read everything and could not tell" call for different human next steps,
which is the same argument `_reason_nothing_was_found` already makes.

*Told, not silently truncated:* when a bound is one turn from binding, the loop says so
in the tool result. A model that gets one more turn's warning can spend it emitting its
best current answer instead of a seventh log read. This is a hint, not a contract - the
loop still cuts at the bound whatever the model does with the warning.

### The tools are the read client's functions, described

`read_mcp_client` already exposes each read-tier tool as a real typed function. The
Investigator wraps those three in Anthropic tool definitions - name, description, JSON
input schema - and dispatches a `tool_use` block by calling the matching function.

*Why not point the model at the MCP server directly:* the dispatch table is where the
budget is counted, where the narration is published, and where a nonsense window gets
turned into a tool result the model can recover from rather than an exception that kills
the investigation. That is loop business.

*Windows are the model's, clamping is not.* A requested log window is still held within
`log_max_window_minutes`, and the clamp still gives way at the start rather than the end,
for the reason `_window_around` already documents. The difference is that the model
proposes the window and is *told* when it was clamped, rather than never having had a
say.

### `LLMClient` gains a conversational method; the current one stays

```
def converse(self, messages, tools, max_tokens) -> Turn
```

`Turn` carries the model's text, its requested tool calls, and its token usage.
`propose_hypotheses` is untouched and still used by anything that wants a one-shot
verdict.

*Why add rather than replace:* the eval suite, the contract tests, and
`anthropic_double`'s existing recordings all speak the current method. Replacing it makes
this change a rewrite of three suites before a line of Investigator code runs.

*Why not a raw `complete()`:* `Turn` is a typed domain object, not a provider response.
The adapter still owns wire-format translation, and a double still cannot satisfy the
Protocol by returning a string.

### Testing: three layers, each measuring one thing

1. **Loop tests, scripted stub model.** A stub whose `converse` returns a list of
   pre-written `Turn`s in order. Every budget bound, the `final_answer` path, the
   clamped-window path, the recover-from-a-bad-window path, and the exhaustion outcome
   are all deterministic and need no recording. This is where confidence in the *code*
   comes from, and it is stronger than what exists today.
2. **Eval suite, real model.** Whether the model actually chooses sensible channels and
   windows is a pass rate over scenarios, not an assertion. This is where confidence in
   the *judgement* comes from.
3. **`e2e_replay`, one recorded path.** Proves the wiring end to end for free on every
   push. It proves the pipeline works; it does not prove the model was right, which is
   the same thing it proved before.

*The honest cost:* today a recording is one request/response pair. Under a tool loop it
is a path, and it only replays if the model walks that path again. `e2e_replay` gets more
brittle, and re-recording after a prompt change becomes routine rather than rare. That is
the price of the change and it should be named, not discovered.

## Risks / Trade-offs

- **`anthropic_double` must replay multi-turn exchanges** → It is off-limits to Claude
  and is the evidence the adapter is judged against, so it is a human-written piece of
  this change. It should be built and merged *before* the loop, because nothing
  downstream can be verified without it. Treat it as the critical path.
- **Recordings become path-dependent, so `e2e_replay` gets brittler** → Match a recorded
  turn on the conversation so far rather than on exact request bytes, and make
  re-recording a one-command operation. Accept that a prompt change now invalidates
  recordings.
- **A model that never calls `final_answer` burns the whole budget every time** →
  The one-turn-from-binding warning, plus an eval that measures how often the budget is
  hit rather than only whether the answer was right. A rising budget-exhaustion rate is
  the signal that the prompt has drifted.
- **Non-determinism moves into the control flow, not just the answer** → Two runs of the
  same incident can now read different evidence, so a bug reproduces intermittently. The
  transcript is the mitigation and has to be published, which is also why this change is
  the natural home for `REPLAY_LOG` (spec §4 principle 6).
- **The model can spend the whole budget on one channel** → Accepted. Requiring a spread
  of channels would be re-imposing the schedule under another name, and the case where
  changes alone answer the question is exactly the case this change exists to allow.
- **Cost per investigation is no longer knowable in advance** → The token budget is a
  hard ceiling, so the worst case is bounded even though the typical case is not
  predictable. Set it from the current loop's measured spend at maximum iterations, so
  the ceiling starts no worse than today.
- **Loss of a real property: the current loop provably reads strictly further back each
  iteration** → Gone, and nothing replaces it. The model may re-read a narrower window
  than it already saw. The budget bounds the waste; it does not prevent it.
