## Why

The postmortem's prose cites the labels the prompt gave the evidence, and a
label with a row in the document links to it. Three kinds have no row: a
change to production the walk read (`P2`), a log message it read (`G3fa2`) and
a lead a person wrote (`L1`). So a reader is told "the deploy P2 switched the
categoriser model" and has no way to find out what P2 was.

## What Changes

- The document carries the changes to production and the log messages the
  model was shown, each under the label it was shown by, and each lead carries
  its label.
- Supporting information lists the changes and the log messages as labelled
  rows; What people told Argus shows each lead's label.
- Every label the prose may cite has a row, so every citation links - on the
  page and in the PDF.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `postmortem-template`: Supporting information also holds the changes and
  log messages read, each under its label; every label the model may cite
  has a row.

## Impact

- `argus_core.models`: `PostmortemDocument` gains `changes_read` and
  `log_messages_read`; `PostmortemLead` gains `label`.
- Schema revision `001`: two JSONB columns, edited in place.
- `agent_postmortem.writing`: fills them from the evidence as labelled for the
  prompt.
- `postmortem_rendering`: supporting rows, lead labels, `labels` widened; PDF
  lands citations on the new rows.
- `argus_web` `postmortem.html`: renders the rows with anchors.
- `docs/spec-and-architecture.md` §7.6.
- No re-recording: the prompt and the answer are unchanged.
