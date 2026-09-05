Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it. `Argus-Demo-Target-App` is the
exception - its tests are written after the code, by Claude, directly.

## 1. The bands the demo serves

- [x] 1.1 Pay bands and their job-title assignments in
      `Argus-Demo-Target-App`, in the HR API's own wire shape: levels carrying
      `min`, `mid`, `max`, `currencyCode` and the titles assigned to them.
- [x] 1.2 The titles the scenarios' responders actually hold are covered, and
      at least one title deliberately is not.
- [x] 1.3 Tests in the demo app for the endpoint, written after the code.

## 2. The source

- [x] 2.1 Propose the test: a title resolves to the band of the level it is
      assigned to, out of one fetch of the whole structure.
- [x] 2.2 `modules/responder_rate_source`, reached by base URL, answering
      title -> band, with the credential and URL in `argus_core.config` and
      `.env.example`.
- [x] 2.3 Test: a title no level lists has no rate; a source that cannot be
      read says so, distinguishably.
- [x] 2.4 Those two answers, kept apart all the way out of the module.

## 3. What the response cost

- [x] 3.1 Propose the test: one responder's minutes at their band's midpoint,
      with the range from the band's minimum and maximum.
- [x] 3.2 The working-hours year in `argus_core.config`, defaulting to 2080
      (40 hours x 52 weeks), plus `.env.example`.
- [x] 3.3 The pricing itself in `agent_postmortem`, per responder, summed.
- [x] 3.4 Test: two responders on different bands are priced separately; an
      incident nobody engaged with costs zero.
- [x] 3.5 Test: one unpriced title suppresses the whole figure and names the
      title.

## 4. In the document

- [x] 4.1 Propose the test: the document carries the cost, its range, and the
      assumptions naming the working year and the bands used.
- [x] 4.2 `responder_cost_estimate` and its range on `PostmortemDocument` and
      on the `postmortem` row.
- [x] 4.3 The assumption lines, beside the exchange-rate one already there.
- [x] 4.4 The figures on the incident page, wherever the minutes are shown.

## 5. Running the thing

- [x] 5.1 The HR endpoint joins the Target Environment's compose stack, and
      `e2e_replay` points the source at it.
- [x] 5.2 Test: the replayed e2e stack reaches a postmortem carrying a
      responder cost, for a scenario somebody was paged for.

## 6. Closing out

- [ ] 6.1 `lint`, `typecheck`, `test_all`, `integration`, `e2e_replay`.
- [x] 6.2 Spec §7.6 updated for the figure the document now carries, per the
      `spec-doc-style` skill.
- [ ] 6.3 One-line commit in each repo, approved before it is made, and the
      archive as a second commit in Argus.
