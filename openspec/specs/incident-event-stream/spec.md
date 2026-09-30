# incident-event-stream Specification

## Purpose
What Argus publishes as it works, what is recorded of it, and the guarantees a reader gets - ordering, completeness, and that publishing never alters what an agent decides (§4 principle 8, §11.1).
## Requirements

### Requirement: Argus publishes what it does as it does it

Every component that investigates, decides or acts on an incident SHALL publish a typed event at the moment it does so, carrying what it did and to which incident. Publishing is how a reader learns what happened; a component SHALL NOT be responsible for who reads it.

#### Scenario: An agent is invoked

- **WHEN** the Orchestrator invokes a sub-agent for an incident
- **THEN** an event is published naming the agent and the incident, at the time of the invocation

#### Scenario: A retrieval is made

- **WHEN** a component asks a retrieval channel for metrics, logs or changes
- **THEN** an event is published naming the channel and the window asked for, and a second event carries what came back

#### Scenario: A conclusion is reached

- **WHEN** an onset is detected, a hypothesis is formed, an action is taken, or an incident changes status
- **THEN** an event is published carrying that conclusion and the values it was reached with

### Requirement: Publishing never changes what Argus decides

The event stream SHALL be an account of the work, never part of it. No decision, verdict or action may depend on a published event, and a publisher that fails SHALL NOT fail the incident.

#### Scenario: The stream is unavailable

- **WHEN** publishing an event fails
- **THEN** the investigation continues unchanged and reaches the same conclusion it would have reached

#### Scenario: Nothing is subscribed

- **WHEN** an incident runs with no subscriber attached
- **THEN** the incident completes exactly as it does with one

### Requirement: The stream is recorded per incident, in order

A subscriber SHALL persist published events against the incident they belong to, preserving the order in which they occurred, so an incident's story can be read back after the process that produced it has gone. Recorded events SHALL be append-only: nothing that was published is later amended or removed.

#### Scenario: Reading an incident back after it has finished

- **WHEN** the recorded events of a finished incident are read
- **THEN** they come back in the order they were published, complete from the alert to the last decision

#### Scenario: A reader arrives mid-incident

- **WHEN** the recorded events of a running incident are read
- **THEN** everything published so far comes back, and nothing is withheld pending an outcome

### Requirement: Recording an event does not make a second writer of incident state

Persisting the stream SHALL leave the single-writer rule intact: the subscriber writes events and nothing else, and no publisher writes to the database on its own behalf.

#### Scenario: An event is recorded

- **WHEN** an event is persisted
- **THEN** no incident, hypothesis, action or timeline row is created, modified or deleted as a result

### Requirement: An event carries enough to be read without the code that published it

Each event SHALL be typed and self-describing: what happened, to which incident, when, and the values that make it meaningful - a window's bounds, a channel's name, a candidate's subject, a verdict. A reader SHALL NOT have to know which function published an event to understand it.

#### Scenario: A retrieval event read months later

- **WHEN** a recorded retrieval event is read
- **THEN** it names the channel and both bounds of the window asked for, without reference to the calling code

### Requirement: The transport is not part of the contract

Components SHALL publish through an interface that says nothing about how events travel. Replacing in-process dispatch with a broker SHALL require no change to any publisher or to any reader of the recorded stream.

#### Scenario: The transport is replaced

- **WHEN** the publishing mechanism is changed
- **THEN** no component that publishes an event and no reader of recorded events is modified

### Requirement: An unreachable platform is an event of its own

The system SHALL publish a typed event recording that a platform could not be
reached, carrying the platform and the kinds of action that platform carries, so
that a reader learns what was taken away rather than only that something was.

Self-describing on the same terms as every other event: the action kinds are
carried in the event rather than left to be looked up from the map that holds
them, because an incident read months later is read without the code that
published it, and a platform's name alone tells a reader nothing about what it
cost them.

#### Scenario: The event names the platform
- **GIVEN** an incident in which a platform was found unreachable
- **WHEN** its recorded events are read
- **THEN** one of them names that platform as unreachable

#### Scenario: The event names what the platform took away
- **GIVEN** such an event
- **WHEN** it is read
- **THEN** it carries the kinds of action that act through that platform,
  without reference to the code that published it

### Requirement: It is published where the walk learnt it

The event SHALL be published at the moment the walk learns the platform is
unreachable - after the attempt that discovered it, and before the candidate
that follows - and by the walk rather than by the tier whose call failed.

The stream is read as a story in the order it happened, and an event explaining
why later candidates went untried is only an explanation if it stands before
them. Published by the walk because the walk is what learnt it: the tier
reported a failed call, which is not yet the fact that a platform is
unavailable to this incident, and a tier that published against an incident
would be publishing about work it cannot see the shape of.

#### Scenario: It stands between the attempt and the fall-through
- **GIVEN** an incident in which an attempt failed on an unreachable platform
  and a later candidate was acted on
- **WHEN** the recorded events are read in order
- **THEN** the platform's event follows the failed attempt and precedes the
  events of the candidate that was acted on

#### Scenario: The tier publishes nothing
- **GIVEN** a write-tier call that failed because its platform was unreachable
- **WHEN** the events published by that call are examined
- **THEN** it published none, and the event came from the walk

### Requirement: It is said as one line naming the platform and what it took away

The event SHALL be narrated as a single line naming the platform and the actions
it made unavailable, in the same words wherever the incident is told.

An incident mitigated by the one action on a reachable platform reads, without
this line, as though Argus simply preferred that action - which is the record
misstating the reasoning it exists to hold. One line rather than a line per
candidate, because the fact is about the platform: repeated per candidate it
teaches a reader to skim exactly the sentence that explains the outcome.

#### Scenario: What is said names the platform and the actions
- **GIVEN** a recorded unreachable platform
- **WHEN** the event is narrated
- **THEN** the line says that platform could not be reached and which actions
  were unavailable while it could not

#### Scenario: Every destination says it the same way
- **GIVEN** an incident whose platform was unreachable
- **WHEN** the incident is told on the dashboard, in Slack and in its postmortem
- **THEN** the line is the same in each
