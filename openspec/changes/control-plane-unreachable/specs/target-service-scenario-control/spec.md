## ADDED Requirements

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
mode, and one about detection rather than about acting - so staging it here
would leave this change's whole claim untested while appearing to pass.

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
