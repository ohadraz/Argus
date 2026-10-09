## Why

Today the only thing a person can tell Argus is "stop" (withdraw), and that
undoes everything Argus changed. When a person reports that the incident is
over, Argus has to accept it: stop working, leave everything as it is, and
write the incident up. Spec §16 already says this ("a person saying the
incident is over ... that report is the fact"), but nothing implements it.

This is the second of three changes. Change (a) made stopping prompt. This one
adds the resolution itself and its first channel, a button in the Argus UI.
Change (c) adds PagerDuty as the second channel.

## What Changes

- A person can report an incident resolved from the Argus UI, with an optional
  free-text note. This is accepted from every status except `resolved`,
  `withdrawn` and `disproven`, including the terminal `mitigated`, `escalated`
  and `recommended`.
- The incident becomes `resolved`. Argus records who reported it, through which
  channel, when, and the note. The UI's resolver is "demo user". `resolved`
  keeps meaning "resolved, whoever decided it". Who decided it is recorded
  beside the status, not in it.
- A walk that is running stops the step it is in, as it does for a withdrawal.
  It then remembers what was tried and writes the postmortem. It does not run
  Code-Fix, and it does not put back any change it made.
- An incident whose walk had already finished (for example `escalated` with its
  postmortem written) is only marked. The postmortem is not rewritten. The
  postmortem page shows the resolution beside the document.
- The postmortem of an incident a person resolved dates recovery from the
  report, not from the series.
- The walk can no longer write over `resolved`, just as it cannot write over
  `withdrawn`.
- A withdrawal also records who did it and through which channel ("demo user",
  Argus UI).

## Capabilities

### New Capabilities

- `human-resolution`: a person reports an incident resolved; what is accepted,
  what is recorded, what the walk does and does not do afterwards, and what the
  postmortem says.

### Modified Capabilities

- `incident-withdrawal`: the withdrawal records who withdrew the incident and
  through which channel.
- `incident-postmortem`: a human resolution is an ending that gets a
  postmortem, even though the walk did not derive it.

## Impact

- `argus_core`: `StatusChanged` gains an optional `reported` field (who,
  channel, note), along with a `ReportChannel` enum.
- `argus_incidents`: a new `resolution.py` beside `withdrawal.py`. It marks the
  incident, with a guarded UPDATE, and publishes. `incidents.transition` also
  refuses to write over `resolved`. The "still wanted" question becomes "has a
  person ended this, and how".
- `orchestrator`: the routers send a resolved incident to remembering and the
  postmortem instead of to END. The worker unwinds only on a withdrawal, never
  on a resolution, and that includes a walk that fails after the resolution.
  The postmortem's recovery time comes from the report.
- `argus_narration`: a status change a person reported is said in that
  person's name, through that channel, with the note.
- `argus_web`: a `POST /incidents/{id}/resolve` endpoint with an optional note,
  a resolve control beside withdraw, and the resolution shown on the
  postmortem page.
- No schema change. The report travels in the event's JSON. No new recording:
  the e2e case seeds a subset of an existing corpus.
