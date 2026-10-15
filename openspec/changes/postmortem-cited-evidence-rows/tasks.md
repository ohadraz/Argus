## 1. The document carries the evidence

- [x] 1.1 Failing test (`agent_postmortem` `test_writing`, `test_prompting`): the document carries the changes and log messages shown, each under its label, and each lead its label
- [x] 1.2 `PostmortemDocument.changes_read`, `.log_messages_read`; `PostmortemLead.label`; `writing` fills them from the evidence by kind
- [x] 1.3 Failing test (`argus_incidents` postmortem repository): both lists and a lead's label survive the round trip
- [x] 1.4 Revision `001`: `changes_read` and `log_messages_read` JSONB columns

## 2. Every cited label has a row

- [x] 2.1 Failing tests (`postmortem_rendering`): Supporting information lists both, labelled, with the empty sentence; a lead item carries its label; `labels` holds `P`, `G` and `L`
- [x] 2.2 `supporting`, `leads`, `rendering.labels`
- [x] 2.3 Failing test (`test_pdf`): a `P` citation in the root cause lands on its row
- [x] 2.4 PDF draws the rows and lands their citations
- [x] 2.5 Failing test (`argus_web` component): the page's `P2` citation links to a row with id `P2`
- [x] 2.6 `postmortem.html` renders the rows and lead labels with ids

## 3. Close

- [x] 3.1 `docs/spec-and-architecture.md` §7.6
- [x] 3.2 lint, typecheck, guard_layering, affected `test_module`s, `e2e_replay(mode='both')`
