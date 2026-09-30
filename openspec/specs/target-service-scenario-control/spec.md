# target-service-scenario-control Specification

## Purpose
TBD - created by archiving change target-service-scenario-and-logs. Update Purpose after archive.
## Requirements
### Requirement: A registry of pre-seeded scenarios exists, each simulating a different incident cause
The system SHALL maintain at least two scenarios, each identified by a scenario
id and each staging what a real incident of that cause would have produced. A
scenario SHALL declare how its content is produced: either a fixed list of log
entries authored in advance, or generation from a live condition the scenario
seeds and anything may subsequently change. Where a scenario is generated, its
content for a given minute SHALL be derived from the state of that condition
during that minute, and SHALL NOT be authored in advance.

#### Scenario: The feature-flag-toggle scenario reads as a flag-caused error spike
- **GIVEN** the `feature-flag-toggle` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe an elevated error rate arising from
  the feature flag being on

#### Scenario: The bad-deployment scenario reads as a deployment-caused latency spike
- **GIVEN** the `bad-deployment` scenario is activated
- **WHEN** `GET /logs` is requested
- **THEN** the returned log entries describe a deployment and a resulting
  latency spike

#### Scenario: A generated scenario's content follows its condition
- **GIVEN** a scenario whose content is generated from a live condition
- **WHEN** that condition changes and `GET /logs` is requested again
- **THEN** the content for minutes after the change reflects the new state of
  the condition

### Requirement: Scenario control can activate a pre-seeded scenario by id, reset it, and report status
The system SHALL provide `POST /scenario/seed` (activates a named scenario), `POST /scenario/reset` (deactivates the current scenario), and `GET /scenario/status` (reports which scenario, if any, is currently active).

#### Scenario: Seeding a known scenario id activates it
- **GIVEN** no scenario is currently active
- **WHEN** `POST /scenario/seed` is called with a known scenario id
- **THEN** `GET /scenario/status` reports that scenario id as active

#### Scenario: Seeding an unknown scenario id fails
- **GIVEN** no scenario is currently active
- **WHEN** `POST /scenario/seed` is called with a scenario id that isn't in the registry
- **THEN** it responds with an error status and no scenario becomes active

#### Scenario: Resetting deactivates the current scenario
- **GIVEN** a scenario is currently active
- **WHEN** `POST /scenario/reset` is called
- **THEN** `GET /scenario/status` reports no scenario as active, and subsequent `GET /logs` requests return an empty list

### Requirement: `/logs` returns the active scenario's full pre-seeded log content
The system SHALL expose `GET /logs` on the Target Service, returning the
currently active scenario's complete log content for the period it covers,
unfiltered, in chronological order - or an empty list if no scenario is active.
For an authored scenario that content is its pre-seeded list; for a generated
scenario it is the lines its condition produced over that period.

#### Scenario: No scenario active returns no logs
- **GIVEN** no scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns an empty list

#### Scenario: An active scenario's logs are returned in full
- **GIVEN** a scenario is currently active
- **WHEN** `GET /logs` is requested
- **THEN** it returns that scenario's complete log content for the period it
  covers, unfiltered, in chronological order

#### Scenario: Switching the active scenario switches the returned logs
- **GIVEN** the `feature-flag-toggle` scenario is active and `GET /logs` has been requested
- **WHEN** `POST /scenario/seed` is called with the `bad-deployment` scenario id
- **THEN** a subsequent `GET /logs` request returns the `bad-deployment` scenario's log entries, not the previous scenario's

### Requirement: Scenario log entries carry timestamps anchored to seed time
The system SHALL timestamp every scenario log entry, deriving each timestamp
from the instant the scenario was seeded or from the clock as the scenario
progresses, rather than from an absolute literal authored into the fixture, so
that a freshly seeded scenario always reads as recent.

#### Scenario: Entries are timestamped relative to when the scenario was seeded
- **GIVEN** a scenario is seeded via `POST /scenario/seed`
- **WHEN** `GET /logs` is requested
- **THEN** each returned entry carries a timestamp derived from the seed
  instant or from the time that has elapsed since it

#### Scenario: Already-elapsed minutes read the same on re-reading
- **GIVEN** a scenario was seeded and `GET /logs` has already been requested
- **WHEN** `GET /logs` is requested again later, without re-seeding
- **THEN** the entries for minutes that had already completed at the time of the
  first request are unchanged, while minutes that have elapsed since may carry
  new entries

### Requirement: Each scenario serves per-minute metric buckets
The system SHALL provide `GET /metrics`, returning the active scenario's
per-minute buckets for the period it covers - each carrying its minute, error
rate, p50 and p95 latency, request volume, memory used, memory limit and
process start time - with no filtering and no query parameters, mirroring
`GET /logs`. For a generated scenario the buckets are derived from the state of
its condition during each minute.

#### Scenario: Buckets are returned for the active scenario
- **GIVEN** a scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns that scenario's per-minute buckets for the period it
  covers, unfiltered, in chronological order

#### Scenario: No active scenario yields no buckets
- **GIVEN** no scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it returns an empty list

#### Scenario: Buckets share the log entries' anchor
- **GIVEN** a scenario is seeded
- **WHEN** both `GET /logs` and `GET /metrics` are requested
- **THEN** the minutes covered by the returned buckets correspond to the
  minutes of the returned log entries

#### Scenario: Each scenario's buckets reflect its own failure mode
- **GIVEN** the `feature-flag-toggle` scenario is active in one case,
  `bad-deployment` in another and the memory-leak scenario in a third
- **WHEN** `GET /metrics` is requested for each
- **THEN** `feature-flag-toggle` shows an error-rate spike while the flag is
  on, `bad-deployment` shows a p95 latency spike after the deploy, and the
  memory-leak scenario shows memory climbing minute over minute

### Requirement: A scenario's live condition may be a restart rather than a flag
The system SHALL allow a generated scenario to name a restart as the condition
its telemetry reacts to, in place of a feature flag. A flag is the wrong
condition for a fault that accumulates: the flip would fall hours outside every
window a reader retrieves, so it appears in no change history the reader sees,
and no flag causes a leak in any case.

The restart SHALL be exposed under the scenario-control prefix, SHALL reclaim
what the scenario has accumulated, and SHALL take effect for whoever calls it -
the demo console or Argus through the write tier - so that the telemetry cannot
distinguish who restarted the service.

#### Scenario: Restarting resets what the scenario accumulated
- **GIVEN** a staged scenario whose resource usage has climbed
- **WHEN** the restart control is called
- **THEN** the next buckets report usage back at its baseline and a changed
  process start time

#### Scenario: The accumulation begins again after a restart
- **GIVEN** a staged scenario that has just been restarted
- **WHEN** several minutes pass and `GET /metrics` is requested
- **THEN** usage is climbing again from the baseline, because the fault is
  still in the deployed code

#### Scenario: A restart by anyone has the same effect
- **GIVEN** a staged scenario whose usage has climbed
- **WHEN** the restart is performed through the demo console in one case and by
  Argus in another
- **THEN** the telemetry that follows is the same in both

### Requirement: The Target Service serves deploy history in a real deployment tool's shape
The system SHALL provide an endpoint returning the active scenario's deploy
history in the response shape of a real continuous-delivery system, so that the
adapter reading it is the same code that would read the real one. The endpoint
SHALL echo back the application name it was asked about, as the real system
does, and SHALL answer from the active scenario regardless of which name that
is.

#### Scenario: A scenario with a deploy reports it
- **GIVEN** the `bad-deployment` scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns a revision history containing that scenario's deploy,
  carrying the minute it was deployed and the revision deployed

#### Scenario: A scenario without a deploy reports none
- **GIVEN** the `feature-flag-toggle` scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns an empty revision history, so that a deploy is not
  offered as a candidate cause for an incident no deploy caused

#### Scenario: No active scenario yields no history
- **GIVEN** no scenario is active
- **WHEN** the deploy history endpoint is requested
- **THEN** it returns an empty revision history

#### Scenario: The requested application name is echoed back
- **GIVEN** the deploy history endpoint is requested for some application name
- **WHEN** the response is returned
- **THEN** it identifies the application by the name that was requested

### Requirement: Deploy history shares the scenario's seed anchor
The system SHALL anchor deploy timestamps to the same seed instant as the
scenario's log entries and metric buckets, so that a deploy lands at the minute
of the incident it caused rather than at a fixed date.

#### Scenario: The deploy precedes the symptoms it caused
- **GIVEN** the `bad-deployment` scenario is seeded
- **WHEN** its deploy history and its metric buckets are compared
- **THEN** the deploy's time falls at or before the first bucket whose latency
  departs from the baseline

### Requirement: Seeding a generated scenario establishes its live condition
The system SHALL, when a generated scenario is seeded, put its condition into
the state that scenario stages, and SHALL record when that state began. The
recorded beginning MAY be placed a configured interval in the past, so that an
incident with enough history to be diagnosed exists immediately upon seeding.

#### Scenario: Seeding turns the flag on
- **GIVEN** the flag is off
- **WHEN** `POST /scenario/seed` is called with `feature-flag-toggle`
- **THEN** the flag is on afterwards, as the provider reports it

#### Scenario: An incident exists immediately
- **GIVEN** `POST /scenario/seed` has just been called with `feature-flag-toggle`
- **WHEN** `GET /metrics` is requested
- **THEN** several already-completed minutes carry an elevated error rate,
  without waiting for time to pass

#### Scenario: Seeding is not needed a second time
- **GIVEN** `feature-flag-toggle` was seeded and time has passed
- **WHEN** `GET /metrics` is requested
- **THEN** the minutes that elapsed since seeding also carry an elevated error
  rate, for as long as the flag remains on

### Requirement: Resetting clears a generated scenario's live condition
The system SHALL, when scenario control is reset, return the condition of a
generated scenario to its non-incident state, so that no incident is left
running against the next reader.

#### Scenario: Reset turns the flag off
- **GIVEN** `feature-flag-toggle` is active and the flag is on
- **WHEN** `POST /scenario/reset` is called
- **THEN** the flag is off afterwards, as the provider reports it

#### Scenario: Reset stops the anomaly
- **GIVEN** `feature-flag-toggle` is active
- **WHEN** `POST /scenario/reset` is called and a further minute elapses
- **THEN** `GET /metrics` reports that minute at the healthy baseline

### Requirement: The condition may be changed by anyone
The system SHALL derive a generated scenario's content from the current state of
its condition regardless of who changed that state or how, so that a party other
than scenario control - a human in the provider's console, or an automated agent
- can end the incident.

#### Scenario: An externally reverted flag ends the incident
- **GIVEN** `feature-flag-toggle` is active and the flag is on
- **WHEN** the flag is turned off by a party other than scenario control
- **THEN** subsequent reads of `GET /metrics` show recovery, and
  `GET /scenario/status` still reports the scenario as active

### Requirement: A scenario's live condition may belong to a third party
Scenario control SHALL support a scenario whose condition is the state of a
dependency the shop calls rather than anything inside the deployment. Seeding
it SHALL put that dependency into failure and SHALL touch no flag, no deploy
record and no process. Resetting it SHALL return the dependency to answering.

No mitigation SHALL clear the condition: it is not a flag to revert, not a heap
to reclaim and not a deploy to roll back, which is what makes an incident staged
this way gradeable by telemetry alone.

#### Scenario: Seeding fails the dependency and nothing else
- **WHEN** `upstream-dependency-failure` is seeded
- **THEN** the dependency refuses requests, and the flag provider and deploy
  history record no change

#### Scenario: Resetting restores it
- **GIVEN** the scenario is active
- **WHEN** scenario control resets
- **THEN** no scenario is active, and staging any other one finds the
  dependency answering again

### Requirement: A scenario's live condition may be a deployment platform that will not act
Scenario control SHALL support a scenario whose condition is the Target
Environment's deployment platform refusing to act on its behalf. Seeding such a
scenario SHALL put the platform into that state, and resetting SHALL return the
platform to acting, as seeding and resetting already do for a flag, a heap and a
third party's outage.

A platform that is down is a state the estate is in for the length of the
incident, not a property of one request, so it belongs with the other live
conditions rather than in a control of its own. It is also the only way the
state can be true before the incident is investigated, which is what the walk
has to meet.

#### Scenario: Seeding puts the platform into refusal
- **GIVEN** no scenario is active and the platform acts
- **WHEN** a scenario whose condition is the platform's refusal is seeded
- **THEN** the platform refuses to act afterwards

#### Scenario: Resetting returns it to acting
- **GIVEN** such a scenario is active
- **WHEN** scenario control resets
- **THEN** the platform acts again, and staging any other scenario finds it
  acting

### Requirement: The platform answers that it is unavailable rather than not answering
While the condition holds, the platform SHALL answer the routes it refuses with
the status a server uses to say its own API is unavailable, and SHALL NOT hang,
stall or silently drop the connection.

A hang is the more literal unreachability and the wrong one to stage. Every
attempt would then cost the caller's whole request timeout, on a walk that
reaches for the platform more than once, and a run would spend that timeout
repeatedly to establish what a refusal establishes at once. What is under test
is what Argus does when it is told it cannot act, and a status that says so
tells it in the platform's own words.

#### Scenario: The refused route says the API is unavailable
- **GIVEN** the condition holds
- **WHEN** a state-changing route of the platform is called
- **THEN** it answers that the platform's own API is unavailable

#### Scenario: The refusal is immediate
- **GIVEN** the condition holds
- **WHEN** a state-changing route of the platform is called
- **THEN** it answers well within the timeout a caller would wait, rather than
  by holding the connection open

### Requirement: The platform refuses to act and goes on saying what it holds
The condition SHALL be carried by the platform's state-changing routes alone.
The routes that roll back, restart, scale and change an application's spec SHALL
refuse, while the routes that report an application, its deployment history and
its resources SHALL go on answering exactly as they do with the condition clear.

This is the difference between staging a platform Argus cannot mitigate through
and staging one it cannot see. The deployment that is this incident's first
candidate is found by reading the platform's own history: a condition that took
the reads down as well would hide the deployment, no rollback would be ranked,
and the walk would never reach for the platform at all. That is a different
mode, and one about detection rather than about acting - so a condition that
refused the reads would leave the whole claim untested while appearing to pass.

#### Scenario: The deployment history still answers
- **GIVEN** the condition holds
- **WHEN** the platform's application and deployment history are read
- **THEN** they answer as they do with the condition clear, and the scenario's
  deploy is in the history

#### Scenario: A change to the same application is refused
- **GIVEN** the condition holds, and an application the platform reports on
- **WHEN** that application is asked to roll back, restart, scale or change its
  spec
- **THEN** each is refused

### Requirement: The shop keeps serving while its platform will not act
The condition SHALL touch the platform's routes and nothing else. The Target
Service SHALL go on serving its own requests and reporting its own logs and
metrics, and the flag provider SHALL go on answering and accepting changes,
while the condition holds.

Both of those are load-bearing. A mitigation is judged by reading the service's
own telemetry, so a service that went down with its platform would leave every
mitigation unjudgeable and the incident would end for that reason instead of
this one. And the flag revert is the action the walk is meant to fall through
to: a flag provider that went down alongside would stage two platforms failing
at once, which is an outage rather than this mode.

#### Scenario: The service's own telemetry is unaffected
- **GIVEN** the condition holds
- **WHEN** the Target Service's logs and metrics are read
- **THEN** they are what the active scenario produces, as they are with the
  condition clear

#### Scenario: The flag provider is unaffected
- **GIVEN** the condition holds
- **WHEN** a flag is read and then changed
- **THEN** the provider answers and the change takes effect

### Requirement: A scenario's live condition may be telemetry publishing that has stopped

Scenario control SHALL support a scenario whose condition is the Target Service
no longer publishing its own metrics. Seeding such a scenario SHALL stop the
publishing, and resetting SHALL restore it, as seeding and resetting already do
for a flag, a heap, a third party's outage and a platform that will not act.

Publishing is a state the shop is in for the length of the incident rather than
a property of one request, so it belongs with the other live conditions rather
than in a control of its own. It is also the only way the state can already be
true when the incident is investigated, which is what the walk has to meet: the
minutes before the deployment landed have to exist and the minutes after it
have to not, and no per-request switch can produce a window shaped like that.

The condition SHALL be carried by the deployment the scenario stages, so the
state has a cause that can be returned. It SHALL begin at a minute and end at
one, and rolling the deployment back SHALL end it - which is what makes the
publishing resuming an answer to an action rather than a timer expiring.

#### Scenario: Seeding stops the publishing
- **GIVEN** no scenario is active and the shop publishes metrics
- **WHEN** a scenario whose condition is stopped telemetry publishing is seeded
- **THEN** no bucket is served for the minute the seed fell in, nor for any
  minute after it

#### Scenario: Resetting restores the publishing
- **GIVEN** such a scenario is active
- **WHEN** scenario control resets
- **THEN** buckets are served again for the minutes that follow, and staging
  any other scenario finds the shop publishing

#### Scenario: Status reports the scenario like any other
- **GIVEN** such a scenario is active
- **WHEN** scenario status is read
- **THEN** it names this scenario as the active one

### Requirement: The condition touches the publishing and nothing else

The condition SHALL stop the metrics the shop publishes about itself and SHALL
touch nothing else it does. While it holds, the Target Service SHALL go on
serving its own requests, SHALL go on reporting its logs for every minute, and
the deployment platform SHALL go on answering and accepting a rollback.

All three are load-bearing, and for the same reason the control-plane scenario
states its own: a condition that took anything else down with it would stage a
different incident and leave this change's claim untested while appearing to
pass.

- A shop that stopped serving would be an outage, found the ordinary way, and
  the question this mode exists to ask would not arise.
- Logs that stopped alongside would leave nothing saying the shop is well, and
  Argus would be right to escalate two dead channels rather than diagnose one.
- A platform that stopped answering would take away the action, and the
  incident would end for that reason instead of this one.

#### Scenario: The shop goes on serving
- **GIVEN** the condition holds
- **WHEN** the Target Service's own routes are called
- **THEN** they answer as they do with the condition clear

#### Scenario: The logs are unaffected
- **GIVEN** the condition holds
- **WHEN** the Target Service's logs are read
- **THEN** they carry lines for every minute, including the minutes no bucket
  exists for

#### Scenario: The deployment platform is unaffected
- **GIVEN** the condition holds
- **WHEN** the deployment history is read and a rollback is asked for
- **THEN** the platform answers and the rollback takes effect

### Requirement: The metrics route answers rather than failing

While the condition holds, `GET /metrics` SHALL answer successfully, carrying
the minutes it has and omitting the minutes it does not. It SHALL NOT refuse,
error, hang or drop the connection.

This is the whole of what makes the mode what it is, and it is the one place a
plausible implementation would get it wrong. A route that failed would be an
observability outage: it raises, Argus says which read could not be taken, and
the walk ends with the failure named - which is a mode Argus already handles
and reports correctly. What is staged here is a read that **succeeds** and
carries less than the truth, because that is the only shape in which an absence
is indistinguishable from health.

The response SHALL remain valid against the shape every other scenario serves,
so nothing between the route and the model treats a shortened window as
malformed.

#### Scenario: The route answers successfully while the condition holds
- **GIVEN** the condition holds
- **WHEN** `GET /metrics` is called
- **THEN** it answers successfully

#### Scenario: The answer carries the minutes before the condition began
- **GIVEN** the condition holds
- **WHEN** `GET /metrics` is called
- **THEN** its buckets are the minutes before the condition began, and it
  carries no bucket for any minute at or after it

#### Scenario: The shortened answer is valid
- **GIVEN** the condition holds
- **WHEN** the answer to `GET /metrics` is read by a consumer of that route
- **THEN** it validates against the shape every other scenario's answer takes

