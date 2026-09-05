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

## ADDED Requirements

### Requirement: An incident is walked by a worker, not by the request
The system SHALL run each incident's graph in a process separate from the one
receiving alerts, taking the run from a queue the alert endpoint wrote to. A
queued run SHALL be claimed by exactly one worker, so that two workers running
at once cannot walk the same incident twice.

#### Scenario: A queued run is picked up and walked
- **GIVEN** an incident whose run has been enqueued
- **WHEN** a worker is running
- **THEN** the graph is invoked for that incident, and the incident reaches a
  terminal status without any further request being made

#### Scenario: One run is claimed once
- **GIVEN** a queued run and two workers competing for it
- **WHEN** both attempt to claim it
- **THEN** exactly one of them walks it

### Requirement: A run abandoned mid-walk is resumed rather than restarted
The system SHALL make an unfinished run reclaimable once the worker holding it
is no longer alive, and SHALL resume it against the state already recorded for
that incident rather than beginning it again. A worker still walking a run
SHALL NOT have it taken from it.

#### Scenario: A worker that died leaves a resumable run
- **GIVEN** a run claimed by a worker that stopped mid-walk
- **WHEN** a worker takes it up again
- **THEN** the incident continues from the point its recorded state reached,
  rather than from the alert

#### Scenario: A run in progress is not taken
- **GIVEN** a run claimed by a worker that is still walking it
- **WHEN** another worker looks for work
- **THEN** it does not claim that run

### Requirement: An incident is acknowledged before anyone is on it
The system SHALL record an accepted alert as `acknowledged`: Argus holds the
alert and has committed to handling it, and no investigation has begun. The
incident SHALL become `investigating` when a worker takes its run, and not
before. `acknowledged` SHALL NOT be terminal - an incident sitting there is one
still waiting to be worked, and anything polling it must keep polling.

#### Scenario: An accepted alert is acknowledged, not investigated
- **WHEN** an alert is accepted
- **THEN** the incident's status is `acknowledged`, and its timeline records
  that and nothing further

#### Scenario: The investigation begins when a worker takes the run
- **GIVEN** an incident whose run is queued
- **WHEN** a worker claims it
- **THEN** the incident becomes `investigating`, recorded on the timeline
  before the graph runs

#### Scenario: A queued incident is not treated as finished
- **GIVEN** an incident that has been acknowledged and not yet claimed
- **WHEN** anything asks whether it has ended
- **THEN** it is reported as still running

### Requirement: A failed run is recorded against its incident
The system SHALL record a run that failed, with the reason it failed, and SHALL
leave the incident at the status the graph last reached. A failure SHALL NOT be
reported as a completed incident, and SHALL NOT be discoverable only as a log
line.

#### Scenario: A run that raised is recorded as failed
- **GIVEN** an incident whose graph raises while being walked
- **WHEN** the run ends
- **THEN** the run is recorded as failed with its reason, and the incident is
  not recorded as resolved
