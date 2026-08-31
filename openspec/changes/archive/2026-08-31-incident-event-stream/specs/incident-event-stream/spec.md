## ADDED Requirements

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
