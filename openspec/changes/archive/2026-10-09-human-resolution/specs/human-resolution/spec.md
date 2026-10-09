## ADDED Requirements

### Requirement: A person can report an incident resolved

The system SHALL accept a report that an incident is resolved from any status
except `resolved`, `withdrawn` and `disproven`. The terminal endings `mitigated`,
`escalated` and `recommended` are included: in those endings Argus stopped and
somebody else carried on. The report SHALL be taken as fact and never checked
against the metrics.

The incident SHALL become `resolved` and SHALL record its end time, unless it
already has one. If the walk had already ended the incident, the end stays the
moment the walk ended it.

#### Scenario: A running incident is reported resolved

- **GIVEN** an incident under investigation
- **WHEN** a person reports it resolved
- **THEN** its status becomes `resolved` and its end time is the time of the
  report

#### Scenario: An escalated incident is reported resolved

- **GIVEN** an incident that Argus escalated
- **WHEN** a person reports it resolved
- **THEN** its status becomes `resolved` and its end time is still the time of
  the escalation

#### Scenario: An incident that cannot be resolved

- **GIVEN** an incident that is `resolved`, `withdrawn` or `disproven`
- **WHEN** a person reports it resolved
- **THEN** the report is refused and nothing about the incident changes

### Requirement: Who resolved it, how and when are recorded

The system SHALL record, on the transition to `resolved`, who reported it, the
channel it came through, when, and the person's note if they gave one. A
withdrawal SHALL record who and through which channel in the same way. The
timeline SHALL say the change in that person's name, not in Argus's.

#### Scenario: A resolution from the Argus UI with a note

- **GIVEN** a running incident
- **WHEN** it is resolved from the Argus UI with the note "rolled back by hand"
- **THEN** the timeline records that "demo user" resolved it from the Argus UI,
  with that note

#### Scenario: A resolution without a note

- **WHEN** an incident is resolved from the Argus UI with no note
- **THEN** the resolution is recorded with no note, and nothing stands in for
  one

### Requirement: A resolution stops the walk and changes nothing back

A walk whose incident is resolved SHALL stop at the same points where it stops
for a withdrawal: between model turns, before every change to the world, and at
every node boundary. It SHALL NOT propose or take any further action, and it
SHALL NOT run Code-Fix. Unlike a withdrawal, it SHALL put nothing back: every
change Argus made stays in place and is recorded as still applied. This holds
even if the walk fails after the resolution.

#### Scenario: Resolved during investigation

- **GIVEN** an incident under investigation that has taken no action
- **WHEN** it is resolved
- **THEN** no action is taken, Code-Fix does not run, and the incident ends
  `resolved`

#### Scenario: Resolved after a mitigation was applied

- **GIVEN** an incident whose flag Argus switched off
- **WHEN** it is resolved before the walk ends
- **THEN** the flag stays off, and no undo is attempted or narrated

#### Scenario: A walk that fails after the resolution

- **GIVEN** an incident resolved after Argus changed something
- **WHEN** the rest of its walk raises
- **THEN** the change stays in place and the incident stays `resolved`

#### Scenario: The walk cannot overwrite a resolution

- **GIVEN** a step running when the incident is resolved
- **WHEN** that step finishes and would move the incident
- **THEN** the incident stays `resolved` and no move is announced

### Requirement: A resolution ends in a postmortem, written once

A walk that stops because of a resolution SHALL go on to remember what was
tried and to write the postmortem. An incident that is resolved before any
worker picks it up SHALL still be walked to its postmortem, without being
investigated. An incident whose postmortem was already written SHALL NOT get a
second one. The resolution SHALL be shown beside the postmortem that exists,
whichever came first.

The postmortem of an incident a person resolved SHALL date recovery from the
report rather than search the series for it. A recovery that Argus itself
confirmed before the report SHALL still stand: it is an earlier measurement,
not a contradiction of the report.

#### Scenario: Resolved mid-walk

- **GIVEN** an incident resolved during investigation
- **WHEN** the walk ends
- **THEN** one postmortem is written and its recovery is dated at the report

#### Scenario: Resolved after a confirmed mitigation

- **GIVEN** a mitigated incident resolved while Code-Fix runs
- **WHEN** the walk ends
- **THEN** one postmortem is written, its recovery is the minute Argus
  confirmed, and it lists the mitigation as still applied

#### Scenario: Resolved after the postmortem

- **GIVEN** an escalated incident whose postmortem is written
- **WHEN** it is resolved
- **THEN** no second postmortem is written, and the postmortem page shows who
  resolved it, how, when and the note

#### Scenario: Resolved before anything picked it up

- **GIVEN** an incident whose run is queued
- **WHEN** it is resolved, and a worker then claims the run
- **THEN** it is not investigated, and one postmortem is written

### Requirement: The Argus UI offers resolving

The incident page and the front page SHALL offer a resolve control, with an
optional note, wherever the incident can be resolved. This includes the
terminal statuses that accept it. The endpoint SHALL answer `404` for an
unknown incident and `409` for one that cannot be resolved.

#### Scenario: The control follows the status

- **GIVEN** an incident that is `escalated`
- **WHEN** its page is shown
- **THEN** the resolve control is offered and the withdraw control is not

#### Scenario: A refused resolution is reported

- **GIVEN** an incident already `resolved`
- **WHEN** the resolve endpoint is called for it
- **THEN** it answers `409`
