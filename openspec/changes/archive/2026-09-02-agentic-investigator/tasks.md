## 1. The double (human-written, and smaller than it looks)

`anthropic_double` is off-limits to Claude, so this section is proposed rather than
written. It is short because the double is already turn-agnostic: it never inspects a
request, `_serve` returns the recorded body verbatim, seeds are a FIFO queue, and
recording already numbers successive calls `name`, `name-2`, `name-3`. A `tool_use`
response is just another body. `competing-flag-changes-2.json` and `-3.json` are an
existing multi-turn exchange replaying today.

So the double is **not** the critical path - `argus_core.converse` (§2) is. What §1
actually owes the change is one contract test that stops assuming every recording is a
verdict.

- [x] 1.1 Split `test_a_stored_recording_still_parses_as_a_verdict`. It parametrizes over
      every recording on disk and pushes each through `propose_hypotheses`; a tool-use
      recording makes `parsed_output` `None` and the adapter raise `MalformedVerdict`.
      Branch on the recording's own `stop_reason` so each kind is checked as what it is.
- [x] 1.2 Fix `_State.next_recording_name`'s docstring, which explains the numbering by
      reference to `investigation_max_iterations` - a setting this change deletes. The
      numbering is still right; the reason for it becomes the model's turn count.
- [x] 1.3 Record one real tool-use exchange once §4's tool definitions exist, via the
      existing `/double-control/record` proxy. No new mechanism - the proxy records
      whatever the adapter actually sent, which is the property that makes it worth
      having. `converse`'s integration tests belong to this task rather than to §2:
      there is nothing honest to replay until the recording exists, and a hand-built
      tool-use body would only prove the adapter agrees with our guess about the API.
- [x] 1.4 Repeat the last seed only when it is a terminal turn. **Decided:** a
      `final_answer` - or a legacy `end_turn` verdict - keeps `repeat: null`, which is
      what lets a second round answer without the test knowing how many rounds there
      will be. A retrieval `tool_use` is seeded `repeat: 1` instead, so the queue runs
      dry and the double answers its "nothing queued" 400. Repeating a non-terminal turn
      is never a correct answer: a run needing more turns than were recorded has an
      incomplete recording, and falling off the end says so in one response where
      repeating the same read burns the whole budget and then reports "insufficient
      evidence" - which reads as a prompt problem rather than a short recording. The
      last recording's own `stop_reason` tells them apart, the field the contract test
      already branches on. Land the edit with §1.3, when there is a tool-use recording
      to prove it against; every recording today is a verdict, for which the current
      rule is already right.

## 2. A conversational seam in `argus_core`

- [x] 2.1 Add `Turn` to `argus_core.models`: the model's text, its requested tool calls
      (id, name, typed input), its stop reason, and its token usage. A typed domain
      object, not a passthrough of the provider's response shape.
- [x] 2.2 Add `ToolDefinition` to `argus_core.models`: name, description, JSON input
      schema - the vocabulary a caller uses to offer a tool, independent of Anthropic's
      wire format.
- [x] 2.3 Add `converse(messages, tools, max_tokens) -> Turn` to the `LLMClient`
      Protocol. Leave `propose_hypotheses` in place and unchanged - the eval suite, the
      contract tests and the existing recordings all speak it.
- [x] 2.4 Implement `converse` on `AnthropicLLMClient`, translating `ToolDefinition` to
      the API's tool format and the response back into `Turn`. Wire-format translation
      stays in the adapter.
- [x] 2.5 Update `LLMClient`'s docstring to say why there are now two methods and what
      each is for.
- [x] 2.6 Decide what a turn that is not a normal turn raises, and make each reason its
      own type so a caller has to name the one it handles rather than catching a family
      by accident. Three cases: a **refusal** is final - the same request is declined
      again, so it escalates; a **truncated** turn is recoverable, and whether to buy
      the retry is the loop's call because only the loop knows the budget; a
      **paused** turn cannot happen with client-side tools alone, so it means an
      assumption is wrong and should be loud rather than mistaken for a finished turn.
      `VerdictTruncated` is the wrong name for a conversation that carries no verdict -
      rename to a neutral one shared by both paths, rather than reusing it.

## 3. Budget

- [x] 3.1 Add the three bounds to `Settings`: max tool calls, max cumulative tokens, max
      wall-clock seconds. Document each in `.env.example` with what it protects against.
      Set the token ceiling from the current loop's measured spend at maximum
      iterations, so the worst case starts no worse than today.
- [x] 3.2 Add a round budget to `Settings`, replacing the widening schedule's role in
      bounding the mitigation walk's rounds.
- [x] 3.3 Implement `Budget` in `agent_investigator`: constructed from settings, told
      about each turn's usage, answering "is a bound reached" and "which one", and
      "is this the last turn available".
- [x] 3.4 Retire `investigation_max_iterations` from `Settings` and `.env.example`.

## 4. Tools the Investigator offers

- [x] 4.1 Define the three retrieval tools as `ToolDefinition`s over `read_mcp_client`'s
      typed functions, each taking its own optional window.
- [x] 4.2 Define `final_answer`, whose input schema is the ranked-hypotheses shape
      `propose_hypotheses` returns today.
- [x] 4.3 Implement the dispatcher: name to function, typed arguments in, tool result
      out. It is where the budget is counted and the narration is published.
- [x] 4.4 Handle a call that cannot be served - inverted, empty or over-wide window - by
      returning a tool result the model can recover from, never by raising. Keep a
      change-source failure a failure of the investigation.
- [x] 4.5 Apply the maximum-span clamp to a requested log window, giving way at the start
      rather than the end, and say in the tool result that it was clamped.
- [x] 4.6 Supply the default window when the model names none: for logs, before the onset
      to the alert; for changes, the change lookback ending at the onset.

## 5. The loop

- [x] 5.1 Read metrics and locate the onset before opening the conversation, exactly as
      today. Keep the no-anomalous-minute path short-circuiting without a model call.
- [x] 5.2 Compose the opening message: the alert, the onset, whether the onset is only a
      lower bound and what that means, the refutations from prior rounds, and what
      earlier rounds already read.
- [x] 5.3 Implement the turn loop - call `converse`, dispatch tool calls, append results,
      check the budget between turns.
- [x] 5.4 End on `final_answer` and build `Findings` from its arguments.
- [x] 5.5 End on a bound with the "insufficient evidence" outcome, naming which bound was
      reached in the summary.
- [x] 5.6 Treat a text-only turn as not-an-answer: continue if budget remains, otherwise
      report no determined cause.
- [x] 5.7 Add the one-turn-left warning to the tool result before a bound binds, and cut
      at the bound regardless of what the model does with it.
- [x] 5.8 Rework `Findings`: `can_widen` and `resumes_from` no longer describe a schedule
      position. Replace them with what a next round actually needs.
- [x] 5.9 Delete `agent_investigator/widening.py` and its tests.
- [x] 5.10 Re-shape `retrieval.py` around the tool definitions, and replace
      `reasoning.py`'s single-shot `propose_hypotheses` seam with the conversational one.

## 6. Narration and replay

- [x] 6.1 Publish a retrieval event per tool call, naming the channel and the window
      requested, and a result event carrying what came back.
- [x] 6.2 Record which channels went unread, so "never asked" is distinguishable from
      "asked and empty" on the incident record.
- [x] 6.3 Land `REPLAY_LOG` (spec §4 principle 6) on this narration - it is the natural
      home for it, and non-deterministic control flow makes it necessary rather than
      merely principled.

## 7. Callers

- [x] 7.1 Update the orchestrator's investigating node for the new `Findings` shape. Its
      contract with the FSM does not change - it still receives ranked candidates.
- [x] 7.2 Update the mitigation walk to bound rounds by the round budget instead of the
      widening schedule, and to carry forward what was read as well as what was refuted.

## 8. Tests

Under the TDD policy, tests in `tests/`, `argus_testkit` and `anthropic_double` are
proposed in chat and added by the human. Module tests under `modules/agent_investigator/`
follow the same rule: proposed whole, never as fragments.

- [x] 8.1 Build a scripted stub model: a `converse` returning pre-written `Turn`s in
      order. Injected as a default-argument seam, `create_autospec`-friendly, no
      `patch()`.
- [x] 8.2 Propose loop tests against it: each budget bound, the `final_answer` path, the
      text-only turn, the invalid window, the clamped window, the unread-channel record,
      and the exhaustion outcome naming its bound.
- [x] 8.3 Propose the two tests that hold §2.6's contract to the loop, since an exception
      can always be swallowed and nothing in the type system stops it: a truncated turn
      is retried while budget remains, and escalates when it is not. A refusal escalates
      without a retry either way.
- [x] 8.4 Remove the tests that pin the widening schedule and the fixed iteration count.
- [x] 8.5 Add eval scenarios measuring judgement as a pass rate: does the model widen
      when the onset is a lower bound, does it read changes when they are the answer,
      how often does it exhaust the budget. The thresholds are inherited from the
      single-shot prompt and marked provisional in the file: nothing has been measured
      against the loop yet, and they are meant to be re-set from what it scores.
- [x] 8.6 Re-record and confirm `e2e_replay` stays green on one recorded path.
- [x] 8.7 Run the paid `e2e` once against the real model before merge.

## 9. Documentation

- [x] 9.1 Update `docs/spec-and-architecture.md` §9, §10 and §16 to describe the loop as
      it is now designed - as specification, not as a record of what changed.
- [x] 9.2 Update `CLAUDE.md` if the module layout moved.
