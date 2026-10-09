## Context

A person can end an incident in only one way today, the withdrawal:
`argus_incidents.withdrawal` marks the row, and the walk learns of it from
`IsStillWanted` (status ≠ `withdrawn`). It asks that question in these places:

- `with_status`, before and after every node;
- the routers, through `stopping_when_withdrawn`;
- the agents, as the zero-argument `StillWanted` that change (a) threaded in;
- the worker, before and after the walk.

When the answer is no, the worker **unwinds**. On a walk that fails it
unwinds as well, and unconditionally.

A resolution has to stop the walk as promptly as a withdrawal does. It then has
to go somewhere a withdrawal never goes, to remembering and the postmortem, and
it must never unwind. Read as a plain "not wanted", it would be routed to END
and unwound, which is exactly the trap the docstring of `_is_still_wanted`
describes.

`incidents.transition` refuses to write over `withdrawn` (26f0a92), and it does
so inside the UPDATE itself.

## Goals / Non-Goals

**Goals:**
- A person resolves an incident from the Argus UI, with an optional note. The
  report is recorded with who, which channel and when.
- A running walk stops, puts nothing back, skips Code-Fix, remembers, and writes
  the postmortem. A walk that already finished is only marked.
- Withdrawal records who and which channel in the same way.
- Change (c) adds PagerDuty as one more `ReportChannel` and one more caller of
  `resolve_incident`, with nothing else reshaped.

**Non-Goals:**
- PagerDuty, `incident_reference` and engagement on the real PagerDuty id, all
  of which belong to change (c).
- Authentication. The resolver is "demo user" until Argus has users.
- A time the person states ("it recovered at 14:02"). The report's own time is
  what is recorded.
- Rewriting or exporting a postmortem that is already written.

## Decisions

### D1. One question, which says how a person ended the incident

`IsStillWanted` / `wanted_via` are replaced by
`EndedByAPerson = (incident_id) -> IncidentStatus | None`, with factory
`ended_by_a_person_via(connections)`. It answers `withdrawn`, `resolved`, or
`None` while nobody has ended the incident. It lives in a new
`argus_incidents.ending` module, because it concerns both doors.

- The nodes keep their `IsStillWanted` (bool), which moves into
  `argus_incidents.ending`, and the agents keep their kernel `StillWanted`. The
  graph hands the nodes `wanted_until_a_person_ends_it(ended)` - "nobody has
  ended it" - so a resolution stops them at every point a withdrawal does, and
  no node or agent changes.
- `with_status` and the routers read the ending itself: `withdrawn` → END,
  `resolved` → remembering.
- Worker: walk unless `withdrawn`; unwind only on `withdrawn`. On failure it
  unwinds only if the incident is not `resolved`. This is the one place a
  resolution could otherwise undo what it promised to leave alone.

`resolved` is read as "ended by a person" because the walk never derives it
(`status_after`). If that ever changes, the walk would be at its end anyway.

*Alternative:* keep `IsStillWanted` and add a second question. That is two
reads per check, and two answers that can disagree in between.

### D2. Routing a resolution

- `stopping_when_withdrawn` becomes `stopping_when_a_person_ended_it`:
  `withdrawn` → `WITHDRAWN_ROUTE` (END), `resolved` → `RESOLVED_ROUTE`. Every
  router mapping gains `RESOLVED_ROUTE: REMEMBERING_NODE`.
- `with_status`, on a person's ending, writes nothing and returns the node's
  updates with `status` set to that ending, as it already does for
  `withdrawn`.
- The postmortem node stops only for `withdrawn`. `with_status` takes the set
  of endings that stop its node; every node passes both except the
  postmortem. Remembering is not wrapped and runs as it does today.
- A run that is queued and then resolved is still claimed and walked. The very
  first `with_status` (investigator) sees `resolved` and routes straight to
  remembering. The entrypoint's `investigating` write is refused by the guard
  (D3).

### D3. The guard covers `resolved`

`incidents.transition` refuses to write over `withdrawn` **or** `resolved`.
That covers every late writer: the walk, the entrypoint, and the worker's
`escalated` on failure.

### D4. Marking: `incidents.resolve` + `resolve_incident`

- `incidents.resolve(conn, id)` is one guarded UPDATE: `status = resolved`,
  `ended_at = COALESCE(ended_at, now())`, `WHERE status = ANY(<resolvable>)`.
  It commits and returns a bool, as `withdraw` does.
- `IncidentStatus.accepts_resolution()` is the one statement of which statuses
  may be resolved: all except `resolved`, `withdrawn` and `disproven`. Both the
  UPDATE and the template use it.
- `argus_incidents.resolution.resolve_incident(id, reported, connections,
  publisher) -> bool` publishes `StatusChanged(resolved, reported=...)`, and
  only when the row moved.

`COALESCE` keeps the end of an incident Argus had already ended. The
postmortem is not rewritten, and an `ended_at` that moved would put it out of
step with its own durations and costs.

### D5. Recording who: `Report` on `StatusChanged`

- `argus_core.models.Report(by: str, channel: ReportChannel, note: str | None)`
  and `ReportChannel(StrEnum)`, with `ARGUS_UI = "argus-ui"` for now.
- `StatusChanged` gains `reported: Report | None = None`. "When" is the event's
  own `at`.
- `withdraw_incident` takes a `Report` in place of its `actor`.
- The web endpoints build `Report(by="demo user", channel=ARGUS_UI, note=...)`.

This needs no schema change, because events are stored as JSON and old rows
read back with `reported=None`.

*Alternatives:* a `resolution` table, which would be a second account of
something the event already says; a new event kind, which would be two lines
for one act.

### D6. Narration says it in the person's name

`a_narration_line` for a `StatusChanged` that carries `reported` uses `who =
reported.by`. The text is "Resolved the incident from the Argus UI", followed by
`: <note>` when there is a note, and "Withdrew the incident from the Argus UI"
for a withdrawal. The page, Slack and the postmortem timeline all pick this up
unchanged.

### D7. Postmortem evidence

- `_when_it_came_back` keeps the last confirmed `RecoveryChecked` minute when
  there is one. Otherwise it uses the `at` of the person's `resolved`
  `StatusChanged`, so the series is not searched (§16).
- `_what_was_done` says whether each action was put back (it has a
  `ChangeUndone`) or is still in place. After a resolution nothing is put back
  except Mitigation's own undo of a refuted change.
- No change to the agent's prompt. The resolution reaches the model through
  the timeline line (D6).

### D8. The UI

- `POST /incidents/{id}/resolve`, with an optional form field `note`. It
  answers `404` for an unknown incident and `409` for one that cannot be
  resolved, mirroring `withdraw`.
- `resolve.html` holds a short note input and a button, in the header slot
  beside withdraw. It is shown when `incident.status.accepts_resolution()`.
  On success the server answers `HX-Refresh: true`. A terminal incident's page
  has stopped polling, so the page has to reload itself to show the change.
- The postmortem page reads the person's `resolved` `StatusChanged` and shows
  who, the channel, when and the note above the document.

### D9. e2e

There is one new case, on feature-flag-toggle: resolve from the UI during
investigation. It seeds answers 1, 2 and 6 of the existing `both-` corpus,
because the walk skips Code-Fix (answers 3-5) and the postmortem must get
answer 6. It asserts that the flag is untouched, the incident is `resolved`,
the postmortem exists, and the timeline names "demo user". The PagerDuty case
comes in change (c).

## Risks / Trade-offs

- [Every router mapping and both route sets change] → this is mechanical, and
  a missing entry is a `KeyError` on the first resolved walk. The graph test
  covers one resolved walk per entry point.
- [The worker's failure unwind now reads the incident] → one more read inside
  an error handler, guarded like the rest of `_put_back_what_it_changed`. If the
  read fails, nothing is unwound: leaving a change in place is recoverable,
  while undoing a resolution's mitigations is the error this change exists to
  prevent.
- [Replay] → under replay the double is a FIFO, so a resolution that skips
  Code-Fix would hand the postmortem answer 3. The e2e case seeds the subset
  (D9). Existing cases are never resolved and are unaffected.

## Migration Plan

None. No schema change, and existing event rows read with `reported=None`.

## Open Questions

None.
