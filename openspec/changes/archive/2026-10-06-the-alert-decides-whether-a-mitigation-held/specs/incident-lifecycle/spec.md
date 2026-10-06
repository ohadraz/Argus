## MODIFIED Requirements

### Requirement: `argus_web` receives the alert webhook and invokes the Orchestrator in-process
The system SHALL expose an alert webhook endpoint on `argus_web` (spec §7.9)
that validates the incoming payload and calls the Orchestrator's entrypoint
in-process (spec §7.1), which creates a new `Incident` row and enqueues the run
of the graph for it. The endpoint SHALL answer as soon as the incident exists,
carrying its id, and SHALL NOT wait for the graph. The web process SHALL NOT
invoke the graph at all: an incident is walked by a worker, so an investigation
outlives the request that asked for it and the connection that delivered the
alert cannot be what a run depends on.

A webhook carrying only `resolved` alerts SHALL NOT open an incident, and one carrying
both SHALL open it from the first alert still firing. A firing alert whose rule identity and
service match the alert of an incident still open SHALL NOT open a new one, and the endpoint
SHALL answer with that incident's id.

#### Scenario: Webhook call starts a new incident
- **GIVEN** `argus_web`'s alert webhook endpoint is running
- **WHEN** a webhook call is received with a valid alert payload
- **THEN** `argus_web` validates the payload and calls the Orchestrator's
  entrypoint in-process, which creates a new `Incident` row with
  `status = acknowledged` and enqueues a run for that incident

#### Scenario: The alert is answered before the investigation is over
- **GIVEN** an alert whose investigation takes longer than a moment
- **WHEN** the webhook call is received
- **THEN** it is answered with the incident's id while the graph has not
  finished, and the answer does not depend on the graph finishing

#### Scenario: A resolved alert opens nothing
- **WHEN** a webhook call carries only `resolved` alerts
- **THEN** no incident is created and no run is enqueued

#### Scenario: A resolved alert ahead of a firing one is passed over
- **WHEN** a webhook call carries a `resolved` alert followed by a firing one
- **THEN** the incident is opened from the firing alert

#### Scenario: A re-firing joins the open incident
- **GIVEN** an open incident opened by a rule
- **WHEN** the same rule fires again
- **THEN** no new incident is created, and the answer is the open one's id

#### Scenario: A firing after the incident closed is a new incident
- **GIVEN** an incident opened by a rule and since closed
- **WHEN** the same rule fires again
- **THEN** a new incident is created

#### Scenario: The same rule firing for another service is a new incident
- **GIVEN** an open incident opened by a rule for one service
- **WHEN** the same rule fires for another service
- **THEN** a new incident is created for that service
