## ADDED Requirements

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
