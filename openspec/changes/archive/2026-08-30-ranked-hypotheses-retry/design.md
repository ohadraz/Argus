## Context

`investigate()` runs a bounded ReAct loop and returns exactly one `Hypothesis`. The loop widens the log window each iteration and **stops at the first answer confident enough to act on**, so a successful investigation usually leaves most of its widening budget unspent. The orchestrator then proposes one action, passes it through the tier gate, takes it, and reads the service back: `CONFIRMED` resolves, `REFUTED` routes to Code-Fix, `ESCALATED` routes to a human.

`take_action` already undoes a refuted action - the write tier's `set_flag` is the same call in both directions - and the `hypothesis` table already carries `tested` and `result` columns that nothing currently fills, because there has only ever been one hypothesis and one attempt.

So the machinery for trying a second candidate mostly exists. What is missing is a second candidate, and a loop to walk to it.

## Goals / Non-Goals

**Goals:**

- The Investigator names more than one candidate when the evidence supports more than one, ordered so the best is first.
- Mitigation tries each in turn, leaving production as it found it between attempts.
- Cheap evidence is exhausted before expensive evidence is bought: the small window's candidates are all *tried* before the window is widened.
- The walk ends for a reason that can be stated - no candidates left and no wider look available - rather than at a number picked in advance.
- A human is paged once, when autonomy is actually out of moves; before that they are kept informed.

**Non-Goals:**

- Code-Fix. The walk ends at a page; what happens after a human reads it is unchanged by this design.
- Concurrent attempts. One experiment at a time, always.
- Ranking by anything but the model's own confidence. Learning which cause types tend to be right is a later change with its own evidence.
- Changing what an individual mitigation *is*. `propose_action` and the tier gate are untouched.

## Decisions

### The model returns alternatives; one call, not one call per candidate

`Verdict` gains an `alternatives` list of the same flat shape it already has. One request yields the best explanation and the runners-up it weighed, which is what "ranked" should mean - competing explanations of the *same* evidence, not answers to different questions.

*Alternative considered:* keep the current shape and collect one verdict per ReAct iteration. Free, but those verdicts answer different evidence windows, and the loop's early stop means the common case yields a list of one.

*Alternative considered:* re-ask after each refutation. Adaptive, but pays a model call per refutation and makes spend unbounded in the length of the walk. This design uses it only when a whole round is spent, which is the point at which the extra call buys something the first call could not have known.

The field is **optional**, exactly as `subject` is, and for the same reason: every committed recording predates it, and refusing them would turn a replayed answer into `MalformedVerdict` and cost the offline suites their evidence.

### Ranking is by confidence, computed here, not trusted from array order

Candidates are sorted by descending confidence, ties keeping the model's order. The model is asked for its ordering and its confidences; where they disagree the numbers win, because the numbers are what the gate already reads. A rank is then a property of the data rather than of how the model happened to serialize its answer.

Candidates below `mitigate_threshold` are **kept but not walked**. They are real findings and belong on the incident for a human to read; they are not confident enough to change production over. A round with no candidate above the threshold is a round with nothing to try.

### `investigate()` returns an `Investigation`, not a bare list

A later round has to resume rather than restart, so it needs to know where the widening schedule stopped. That position is the Investigator's own state, not the orchestrator's, so it travels in the return value: an `Investigation` carrying the ordered candidates and the schedule index the loop reached.

Resuming takes the same shape as starting: `investigate(alert, incident_id, resume_from=..., already_refuted=[...])`. A first round passes neither.

*Alternative considered:* have the orchestrator count rounds and pass a lookback. Rejected - it makes the widening schedule the orchestrator's business, and the schedule exists precisely so that "how far to reach" is never a caller's decision.

### Refutations are evidence, and enter through the prompt

A second round differs from the first in two ways: a wider log window, and the knowledge that specific candidates were tried and did not help. The second is the more valuable one, and it is genuinely new information - the model has never seen it. It enters `Evidence` as its own section, phrased as fact rather than instruction: *the flag `X` was set to `off` at `T`, and the service did not return to baseline.*

Naming a refuted candidate again is then the model contradicting evidence it holds, which is the same failure mode as any other hallucination and needs no special rule to forbid it - only a terminus that notices.

### The walk's terminus

The walk ends when a round produces no untried candidate above the threshold **and** the widening schedule has reached its maximum. Both conditions, because either alone ends it too early: a spent round with budget left should widen, and a schedule at its ceiling that still names something new should try it.

No attempt cap. The set of candidates is bounded by the evidence and the schedule is bounded by configuration, so the walk is finite by construction - and a cap would be a second, arbitrary limit that could only ever stop it while real options remained.

### Undo is confirmed before the next attempt

`take_action` already puts a refuted flag back. This design adds the read that proves it: the provider is asked what the flag now evaluates to, and an undo that cannot be confirmed **ends the walk immediately** with an escalation.

Two experiments overlapping in production is the one way a retry loop can be worse than no retry loop - the second verdict would be measuring both changes and attributing it to one. An unconfirmed undo means Argus does not know what state the world is in, and guessing again from there is not autonomy.

### A war room while there are moves; a page when there are none

The Communicator gains the distinction: an update posted after each refutation, saying what was tried, what it did, and what is next; a page raised once, when the walk terminates without a confirmed fix. A page per refuted candidate would train its readers to ignore pages, which is worse than not sending them.

### An irreversible next candidate is posted and skipped

The tier gate refuses actions with no way back. Today that ends the incident. In a walk it should not: the gate is judging *that action*, and the candidates after it may be perfectly reversible. So a rejected action is posted to the war room - a human may well want to take it by hand - and the walk moves on.

### The graph gains a loop, and the state gains a cursor

`IncidentState` carries the ordered candidates, the index of the one under test, the schedule position, and the refutations so far. `mitigation`'s refuted edge goes to a node that advances the cursor and routes: another candidate → back to the proposal node; none left but budget remains → the investigator node, resuming; neither → the communicator, to page.

Each candidate's row in `hypothesis` records its rank, and its `tested`/`result` are filled as the walk reaches it. The timeline then reads as what it was: several explanations, tried in order, each with what it did.

## Risks / Trade-offs

**Argus reads its own toggles as evidence.** → The change channel reports what changed recently, and after one refuted attempt that now includes Argus's own revert. A later round could blame a flag Argus itself moved, which would turn a retry loop into a machine for chasing its own tail. **Solved, and it must land before the walk does:** Argus gets its own provider credential, so the actor on its writes differs from the shop's and its changes can be excluded by name.

Verified against Unleash 8.1.0 rather than assumed. `POST /api/admin/api-tokens` refuses `type: admin` on this build - its schema accepts only client, backend and frontend - so the token cannot be created through the API. But `created_by` on an event is simply the token's `username` column, and a second admin token inserted with `username = 'argus'` is honoured immediately with no restart: a toggle made with it records `createdBy: argus` while the shop's writes stay `admin`, and the events API exposes the difference. `FlagChange.actor` already maps that field and has only ever been inert because both parties shared one credential. Seeding the token is therefore a one-shot psql container beside the ones the Target Environment already runs - no paid tier, no service accounts, no user session.

**Wall-clock cost.** → Each attempt waits out `mitigation_verification_timeout_seconds` before its verdict. Three candidates is three waits, plus a model call per round. The e2e timeouts are already derived from those settings and will need to account for the walk's length rather than one attempt.

**More production churn.** → Every refuted attempt is two real flag writes. Against the demo fixture that is free; the design's answer for anything else is that the undo is confirmed before the next attempt, so churn is serial and bounded, never overlapping.

**Recordings must carry alternatives to exercise the walk.** → Existing recordings replay as a single candidate, which keeps every current test honest but exercises none of the new path. The replayed suite needs at least one recording whose verdict carries alternatives, or the walk is only ever proven by the paid run.

**A longer walk is a longer time to a human.** → An incident that would have paged after one refutation now pages after the walk. The war-room update is what makes that acceptable: a human watching sees each attempt as it happens and can intervene, rather than waiting in silence.
