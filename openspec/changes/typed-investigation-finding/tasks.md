Argus's own modules are TDD: the test is proposed in chat, the user adds it, then
the implementation follows. `tests/`, `modules/argus_testkit/` and
`modules/anthropic_double/` cannot be written by Claude.

## 1. The hypothesis carries a subject

- [x] 1.1 Add `subject` to `Hypothesis` - optional, `None` by default - and a
      validator rejecting a subject with no `cause_type`. A cause without a
      subject stays legal. Propose the test first.
- [x] 1.2 Add `subject` to the wire `Verdict` in `argus_core.anthropic_llm`,
      described for the model as the specific thing the cause names, and pass it
      through `to_hypothesis`.
- [x] 1.3 Instruct the model, in `SYSTEM_PROMPT`, to fill the subject only with
      an identifier appearing verbatim in the evidence, and to leave it null
      when the cause names nothing specific.
- [x] 1.4 Persist it: a nullable `subject` column on `hypothesis` in
      `argus_core.schema`, written and read by the hypothesis repository.

## 2. Mitigation verifies rather than derives

- [x] 2.1 `propose_action` selects the recorded change whose flag matches the
      hypothesis's subject, and proposes the revert of *that* change - the
      direction still read from the change, not from the hypothesis.
- [x] 2.2 A subject matching no recorded change yields no action, so the
      incident escalates.
- [x] 2.3 A hypothesis with no subject keeps today's behaviour exactly: exactly
      one changed flag acts, zero or several escalate.
- [x] 2.4 Confirm `propose_action` is still pure - no I/O, no model call, no
      retrieval - and still runs ahead of the tier gate.

## 3. End to end

- [x] 3.1 Propose in chat the e2e case this change exists for: two flags changed
      recently, the Investigator names one, and *that* flag is the one reverted
      while the other is left alone.
- [x] 3.2 `nox -s lint typecheck test_all guard_e2e_boundary integration
      contract` green.
- [x] 3.3 `nox -s e2e_replay` green - existing recordings carry no subject, so
      this proves the fallback path still works.
- [x] 3.4 `nox -s e2e` green (paid - ask first). This is the run that exercises
      the new path, since only the live model fills the subject in.
- [ ] 3.5 Watch it once in the browser: stage one flag scenario, reset, stage a
      second, and see the second incident mitigated rather than escalated.

## 4. Commit

- [ ] 4.1 One approved single-line message.
