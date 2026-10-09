Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel,
incident record, narration, the walk, the worker, the web.

## 1. Kernel

- [x] 1.1 `IncidentStatus.accepts_resolution()`: true for every status except
      `resolved`, `withdrawn` and `disproven`
- [x] 1.2 `Report(by, channel, note)` and `ReportChannel.ARGUS_UI` in
      `argus_core.models`
- [x] 1.3 `StatusChanged.reported: Report | None = None`; an event without it
      reads back with `None`

## 2. Incident record

- [x] 2.1 `incidents.transition` refuses to write over `resolved` as well as
      `withdrawn` (real Postgres)
- [x] 2.2 `incidents.resolve`: one guarded UPDATE, `ended_at` kept when already
      set and stamped when not, returns whether it moved (real Postgres)
- [x] 2.3 `resolve_incident` publishes `StatusChanged(resolved, reported=...)`
      only when the row moved
- [x] 2.4 `withdraw_incident` takes a `Report` and publishes it on its
      `StatusChanged`
- [x] 2.5 `EndedByAPerson` / `ended_by_a_person_via` in `argus_incidents.ending`
      replace `IsStillWanted` / `wanted_via`: `withdrawn`, `resolved`, or `None`;
      a missing row reads as `withdrawn`

## 3. Narration

- [x] 3.1 A `StatusChanged` carrying `reported` is said in that person's name,
      through its channel, with the note when there is one, for both resolve
      and withdraw

## 4. The walk

- [x] 4.1 Routes: `RESOLVED_ROUTE`; `stopping_when_a_person_ended_it` sends
      `withdrawn` to END and `resolved` to remembering
- [x] 4.2 `with_status` takes the ending question and the set of endings that
      stop its node. On a stopping ending it writes nothing and returns that
      ending as the status, before the node and after it
- [x] 4.3 The nodes keep their `IsStillWanted`; `wanted_until_a_person_ends_it`
      adapts the ending to it ("nobody has ended it"), so no node or agent
      changes
- [x] 4.4 `graph.py`: every router mapping carries `RESOLVED_ROUTE`; the
      postmortem stops only for `withdrawn`; `assembling.py` threads the new
      question. Graph tests: resolved before the investigator, during
      mitigation and during Code-Fix each reach remembering and the
      postmortem, and Code-Fix does not run

## 5. Worker

- [x] 5.1 Walks unless `withdrawn` (a queued, resolved run is walked); unwinds
      only on `withdrawn`
- [x] 5.2 A failed walk is not unwound when the incident is `resolved`, and is
      not unwound when the read fails

## 6. Postmortem evidence

- [x] 6.1 `_when_it_came_back` falls back to the person's `resolved` time when
      no confirmed recovery minute exists
- [x] 6.2 `_what_was_done` says, for each action, whether it was put back or
      is still in place

- [x] 6.3 Mitigation stopped mid-verification records "the incident was
      withdrawn" even when it was resolved - it holds only the yes-or-no. Word
      it as a person having ended the incident (agent_mitigation, `trying.py`)

## 7. Web

- [x] 7.1 `POST /incidents/{id}/resolve` with an optional `note`: 404 / 409 /
      success with `HX-Refresh`; records "demo user", Argus UI
- [x] 7.2 `withdraw` records "demo user", Argus UI
- [x] 7.3 `resolve.html`, shown where `accepts_resolution()`, on the incident
      page and the front page
- [x] 7.4 The postmortem page shows who resolved it, the channel, when and the
      note

## 8. Spec and docs

- [x] 8.1 `docs/spec-and-architecture.md`: §7.6 (postmortem triggers), §10
      (resolution as a person's ending; it stops the walk without unwinding),
      §16 (recovery dated from the report unless Argus confirmed one)

## 9. Verification

- [x] 9.1 e2e case (user writes it): feature-flag-toggle, resolved from the UI
      during investigation, seeding answers 1, 2 and 6. It asserts the flag is
      untouched, the incident is `resolved`, the postmortem is written and the
      timeline names "demo user"
- [x] 9.2 Cleanup: Check comments, docstrings, jargon, logs and docs are aligned, and that no test is 
      missing, redundant or weak; verify no missing logs, or wrong log level. 
- [x] 9.3 Module suites, typecheck, lint, guard_layering green
- [x] 9.4 `e2e_replay(mode='both')` green, in the background
- [ ] 9.5 Specs synced on archive
