## Why

The postmortem today is a root cause in a sentence or two, a summary, the
assumptions and what it cost. It has no timeline, no account of how the
incident was detected or what triggered it, nothing ruled out, no action items
and no lessons - the sections a postmortem is read for (Google SRE book, ch. 15
and its example; ClickHouse's RCA guidance). Spec §7.6 already promises a
timeline and the actions taken, and the document has never carried either. It
also prints the pay bands behind the response cost, and money at full
`Decimal` precision.

## What Changes

- **The document follows one template**, agreed as a mock: a header with the
  full incident ID and two labelled times (the incident's window and alert; when
  the document was written), then Summary, Impact, Detection, Trigger,
  Resolution, Root cause and contributing factors, Hypotheses considered, Action
  items, Lessons learned, Timeline, What people told Argus, Cost of the
  response, Supporting information and a Review checklist.
- **Code writes everything that is a fact**: every figure, the timeline and its
  four markers, detection, trigger, hypotheses, resolution, the action items
  Argus's own record implies, the numbering of every action item, the links and
  the review checklist's checks.
- **The model writes only prose**, in the same single call with two attempts:
  the summary, the root cause, a causal chain whose every step cites evidence
  by label, contributing factors each naming the action items that answer them,
  proposed action items, and lessons learned.
- **The checks grow**: a chain step citing nothing, or a label Argus never gave,
  is a fault; so is a contributing factor no action item answers, and a number in
  any prose field that does not appear in what the model was given.
- **Action items are numbered `AI-n`** and never edited in Argus: owner and due
  date stay blank for the people who take them on.
- **No pay-band figure appears anywhere** in the document - not the endpoints,
  and not the response cost's range, from which the endpoints follow by
  arithmetic. Both stay stored.
- **Money is shown to two decimal places.**
- **BREAKING** (schema): `checklist_complete` becomes a list of review criteria;
  new columns for the structured sections. Revision `001` is edited in place.

## Capabilities

### New Capabilities

- `postmortem-template`: the sections a postmortem has, in what order, and
  which of them code writes and which the model writes.

### Modified Capabilities

- `incident-postmortem`: the prose check covers every number in every prose
  field, not only currency in the summary; a chain step must cite evidence and
  a contributing factor must be answered; completeness is a set of review
  criteria rather than one flag.
- `responder-cost`: the range is stored and no longer shown.

## Impact

- `argus_core.models` (`PostmortemDocument` and its parts), migration `001`.
- `agent_postmortem`: evidence, prompting, checking, assumptions, writing.
- `orchestrator.gathering`: structured timeline, candidates and actions.
- `argus_incidents` postmortem repository; `argus_web` postmortem view and
  template.
- `docs/spec-and-architecture.md` §7.6.
- e2e: every postmortem case re-recorded, since the tool the model answers
  through changes (paid; one `record` pass per mode).
- Out of scope, later changes: the PDF (fpdf2) with its download button, and
  posting it to the incident's Slack thread.
