Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it.

## 1. Walking skeleton

- [x] 1.1 Propose the end-to-end test: an ended incident with recorded
      evidence, both ports faked with known numbers, a faked model answer, one
      postmortem row written with every figure filled.
- [x] 1.2 Define the two ports in `agent_postmortem` - revenue over a window,
      responder timings for an incident - as Protocols, injected as
      default-argument collaborators.
- [x] 1.3 Make the skeleton test pass with the thinnest real path: gather,
      one model call, one row. No checklist, no absent-figure handling.

## 2. When an incident ended

- [x] 2.1 Add `ended_at` to the `incident` table in `argus_core.schema`.
- [x] 2.2 Stamp it on the transition into a terminal status, in the same
      transaction as the status write, and expose it on the incident row the
      repository returns.
- [x] 2.3 Test: an incident that has not ended records no end time.

## 3. The figures

- [x] 3.1 `tokens_spent`, summed from the incident's own replay-log rows.
- [x] 3.2 Duration, from `created_at` to `ended_at`.
- [x] 3.3 `engineer_minutes` and responder count, from the responder port.
- [x] 3.4 The error-rate delta, from a metrics read whose window spans the
      whole incident rather than reusing what the investigation stored.
- [x] 3.5 The loss estimate: baseline revenue rate x duration x error-rate
      delta x the weight the model supplied.
- [x] 3.6 Test each figure against known inputs, including the arithmetic of
      3.5 with a weight of zero and of one.

## 4. Absent figures

- [x] 4.1 A port that cannot answer leaves its figure absent and records why
      in the assumptions - never zero.
- [x] 4.2 Test: an unreachable revenue source yields an absent estimate, and a
      responder source that answers "nobody" is distinguishable from one that
      could not be read.

## 5. The document

- [x] 5.1 The prompt: the computed figures, the timeline, the ranked
      candidates with their verdicts, the evidence. Asks for root cause,
      assumptions, executive summary, and the revenue weight - and for no
      other number.
- [x] 5.2 One `converse` call producing both bodies as separate fields.
- [x] 5.3 The figures written into the row come from the computation, never
      parsed back out of the prose. Test with prose stating a different figure.
- [x] 5.4 The weight and every absent figure's reason are recorded in
      `assumptions`.

## 6. Termination

- [x] 6.1 Check the answer for missing required fields; where any are missing,
      one further `converse` naming them, and no third attempt.
- [x] 6.1a A currency amount in the executive summary that is not Argus's own
      figure counts as a fault the same way a missing field does - one further
      call naming it. Any amount at all when there is no estimate.
- [x] 6.2 Write whatever came back, setting `checklist_complete` accordingly.
- [x] 6.3 Test: a complete first answer makes no second call; a second
      incomplete answer is still written, marked incomplete.

## 7. Wiring

- [x] 7.1 The graph node persists a real postmortem row through the
      repository, replacing the stub's placeholder dict.
- [x] 7.2 The ports' production wiring: no adapter exists yet, so each is
      unavailable by default and says so - the path 4.1 already covers.
- [x] 7.3 An escalated incident is written up too, recording that no cause was
      identified.

## 8. Closing out

- [x] 8.1 `lint`, `typecheck`, `test_module(module='agent_postmortem')`,
      `test_module(module='orchestrator')`, then `test_all`.
- [x] 8.2 `integration`, and `e2e_replay` in the background.
- [x] 8.3 Spec §7.6 and §21.3 updated to the estimate this actually computes -
      a revenue rate, not a user count - per the `spec-doc-style` skill.
- [ ] 8.4 One-line commit, approved before it is made.
