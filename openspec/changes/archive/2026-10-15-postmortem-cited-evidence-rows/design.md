## Context

The prompt labels evidence by kind (`agent_postmortem.prompting._the_evidence_by_kind`):
narration `T`/`XW`, changes `P`, log messages `G`, candidates `C`, actions
`M`, plus action items `AI-n` and leads `L`. `RenderedPostmortem.labels` -
the set `Run.with_citations` cuts links for - holds only hypotheses, steps
taken, action items and timeline rows. `P`, `G` and `L` stay as bare words.

## Decisions

- **Store the evidence, don't re-derive it.** `PostmortemDocument` gains
  `changes_read` and `log_messages_read: list[CitedEvidence]`, filled in
  `writing` from the same `the_evidence_labelled` list the prompt was built
  from, filtered by kind. Re-deriving at render time would need the incident's
  evidence, which `postmortem_rendering` and `argus_web` do not have, and
  would say what is true now rather than what the model was shown.
  *Alternative:* store only the labels the prose actually cites - rejected:
  every prose field would have to be scanned, and a field missed is a
  dangling citation again. Every piece shown is listed, which is also what
  "evidence read" counts.
- **Filtered by kind through the producers, not by prefix.** `writing` takes
  the `P` list from `_numbered(PRODUCTION_CHANGE_PREFIX, ...)` and the `G` list
  from `grouped(...)` - a public function returning the evidence of each kind
  replaces matching on label spelling.
- **A lead stores its label.** `PostmortemLead.label`, written from
  `labelled(evidence.leads)` where the prompt numbered them, so the renderer
  never numbers leads a second time.
- **Rows live in Supporting information**, as two labelled lists after the
  links, each with the sentence said in its place where empty. Not a section
  of their own: the template's sections are Google's, and this is supporting
  material.
- **`labels` widened** to the new rows and the leads; the page gives each an
  `id`, the PDF lands each citation link on its row, as for the existing rows.

## Risks / Trade-offs

- [A long list of log messages makes Supporting information long] → they are
  grouped by message already, one row per distinct message.
- [Schema change] → revision `001` edited in place; `nox -s schema` drops and
  reapplies, and the e2e stack runs it itself.
