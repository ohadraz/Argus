## 0. Argus writes under its own name

Without this the walk can blame its own revert: the change channel reports what
changed recently, and after one refuted attempt that includes Argus's own write.
Verified against Unleash 8.1.0 - `POST /api/admin/api-tokens` refuses
`type: admin` (its schema takes only client/backend/frontend), but `created_by`
on an event is the token's `username` column, and a second admin token inserted
with `username = 'Argus'` is honoured immediately, no restart. A toggle made with
it records `createdBy: Argus` while the shop's writes stay `admin`, and the
events API exposes it. `FlagChange.actor` already maps that field. The provider
caches a token's name on first use, so `token_name` is seeded to match rather
than corrected later.

- [x] 0.1 A compose one-shot seeds a second admin token - `username: Argus` -
      the way `flag-state-seed` seeded flag state: psql, because the API will not
      create an admin token on this build. It belongs to the Target Environment's
      compose file, beside the tokens already seeded there.
- [x] 0.2 The write tier authenticates with that token instead of the shop's.
- [x] 0.3 Change events whose `actor` is Argus are excluded from what a later
      round is offered as candidate causes, with a test proving a flag Argus
      itself moved is never blamed for the incident it was mitigating.
- [x] 0.4 `FlagChange.actor`'s comment stops saying the field is not
      load-bearing, because it now is.

## 1. Ranked candidates in the domain

- [x] 1.1 `Hypothesis` gains `rank`, and the `hypothesis` table a `rank` column.
- [x] 1.2 `Verdict` gains an optional `alternatives` list of the same flat shape;
      `to_hypothesis` becomes `to_hypotheses`, returning the primary and its
      alternatives ordered by descending confidence, ties keeping model order.
- [x] 1.3 An alternative that is incoherent - a subject with no cause, a cause
      with no confidence - fails the whole verdict as malformed, as the primary
      answer does.
- [x] 1.4 `SYSTEM_PROMPT` asks for alternatives, says what makes one, and says an
      empty list is a valid answer.
- [x] 1.5 `nox -s "test_module(module='argus_core')"` green, including a
      recording with no `alternatives` field still replaying.

## 2. The Investigator returns and resumes

- [x] 2.1 `investigate()` returns `Findings` - ordered candidates plus the
      schedule index the loop reached - instead of one `Hypothesis`. Named for
      what an investigation produced rather than for the process, and not
      `Investigation`, which the module's own suite already uses for its
      harness.
- [x] 2.2 An investigation that identified no cause reports it as its one
      candidate, carrying the reason. The list is never empty; actionability is
      the threshold's business.
- [x] 2.3 `investigate()` accepts `resume_from` and `already_refuted`, resuming
      the widening schedule rather than restarting it.
- [x] 2.4 `Evidence` carries the attempts already made; `build_prompt` renders
      them as fact - what changed, to what state, and that the service did not
      recover.
- [x] 2.5 `nox -s "test_module(module='agent_investigator')"` green.

## 3. Mitigation confirms its undo

- [x] 3.1 No code needed - the guarantee already exists, one layer down and
      stronger than the re-read this task imagined. The write tier's `set_flag`
      polls until the change is visible to *evaluation* and raises `FlagNotSet`
      otherwise, so an undo that did not take effect never returns quietly.
      `_undone` catches it and answers `ESCALATED`, which `_status_after` turns
      into an escalation - the walk cannot continue past an undo it could not
      confirm. Covered by `test_an_undo_that_fails_escalates_carrying_both_facts`.
- [x] 3.2 `nox -s "test_module(module='agent_mitigation')"` green.

## 4. The walk, in the graph

- [x] 4.1 `IncidentState` carries the candidates, the index under test, the
      schedule position, and the refutations so far.
- [x] 4.2 The proposal, gate and mitigation nodes read the candidate under test
      rather than `state.hypothesis`.
- [x] 4.3 A gate rejection records, posts, and advances to the next candidate;
      it ends the incident only when no candidate remains.
- [x] 4.4 A refuted outcome advances the cursor and routes: next candidate →
      proposal; none left with budget remaining → investigator, resuming; neither
      → communicator.
- [x] 4.5 An unconfirmed undo, and an outcome that could not be taken at all,
      end the walk immediately.
- [x] 4.6 Every candidate's row is written with its rank, and `tested`/`result`
      are filled as the walk reaches it.
- [x] 4.7 The graph now has a real cycle, so its traversal budget is derived
      from the walk's own bounds rather than left at LangGraph's default of 25 -
      a number three rounds of four candidates passes legitimately. The
      candidate list is capped for the same reason: the budget can only be
      derived if the walk's length is not the model's to choose.
- [x] 4.8 `nox -s "test_module(module='orchestrator')"` green.

## 5. Telling a human

- [x] 5.1 The Communicator gains a war-room update distinct from a page.
- [x] 5.2 An update is posted per refused or refuted attempt while moves remain;
      exactly one page is raised when the walk ends without a fix.
- [x] 5.3 `nox -s "test_module(module='agent_communicator')"` green.

## 6. Evidence for the replayed suite

- [x] 6.1 Record a verdict carrying alternatives, so `e2e_replay` exercises the
      walk rather than only the single-candidate path. Recording is the human's
      to make - `anthropic_double` is off-limits to Claude.
- [x] 6.2 The e2e red-herring case's expectation changes: it asserts the walk's
      behaviour rather than `fixing` after one refuted action.
- [x] 6.3 e2e timeouts account for a walk of several attempts rather than one.

## 7. Green, and seen

- [x] 7.1 `nox -s lint typecheck test_all guard_e2e_boundary integration
      contract` green.
- [x] 7.2 `nox -s e2e_replay` green.
- [x] 7.3 `nox -s eval` green (paid - ask first): the prompt changed, so cause
      detection could have moved for unrelated reasons.
- [x] 7.4 `nox -s e2e` green (paid - ask first).
- [ ] 7.5 Watch it once in the browser: stage the red-herring scenario and see
      Argus try, undo, report, and try again rather than stopping at one.

## 8. Commit

- [ ] 8.1 One approved single-line message.
