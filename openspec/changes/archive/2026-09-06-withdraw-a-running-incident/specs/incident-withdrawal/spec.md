## ADDED Requirements

### Requirement: A live incident can be withdrawn

The system SHALL allow a live incident to be withdrawn, meaning a human has
taken it back and Argus is to stop working on it. Withdrawal SHALL be accepted
for any non-terminal incident and SHALL be refused for a terminal one, so that
withdrawal cannot undo a mitigation that is confirmed and holding the service
up. Withdrawing an already-withdrawn incident SHALL be accepted and change
nothing further.

#### Scenario: A running incident is withdrawn

- **GIVEN** an incident that has not reached a terminal status
- **WHEN** it is withdrawn
- **THEN** its status becomes `withdrawn` and its timeline records that a human
  withdrew it

#### Scenario: A finished incident cannot be withdrawn

- **GIVEN** an incident that has reached a terminal status
- **WHEN** it is withdrawn
- **THEN** the request is refused, the status is unchanged, and nothing Argus
  did is undone

#### Scenario: Withdrawing twice does nothing twice

- **GIVEN** an incident already withdrawn
- **WHEN** it is withdrawn again
- **THEN** the request is accepted, and no action is undone a second time

### Requirement: A withdrawn incident is not walked further

The walk SHALL check whether its incident has been withdrawn at every node
boundary and on every pass of the loop that waits for a service to recover, and
SHALL stop rather than begin its next step. A model call already in flight SHALL
be allowed to return, and its answer SHALL NOT be acted on.

The walk SHALL NOT propose an action, take an action, investigate a further
round, or write a postmortem for a withdrawn incident.

#### Scenario: The next node does not run

- **GIVEN** an incident withdrawn while a node is running
- **WHEN** that node returns
- **THEN** no further node runs, and no action is proposed or taken

#### Scenario: A wait for recovery is cut short

- **GIVEN** an incident withdrawn while its mitigation is waiting out the
  verification window
- **WHEN** the wait next re-reads the metrics
- **THEN** the wait ends without a verdict, within one interval of the
  withdrawal rather than at the end of the window

#### Scenario: An answer that arrives after the withdrawal is not acted on

- **GIVEN** a model call in flight when the incident is withdrawn
- **WHEN** the call returns
- **THEN** its answer is recorded as received and nothing is done with it

### Requirement: A withdrawn incident is not claimed

A worker SHALL NOT claim a run whose incident has been withdrawn, and SHALL
settle such a run without walking it. An incident withdrawn before anything
picked it up SHALL never be investigated.

#### Scenario: A queued run for a withdrawn incident is never walked

- **GIVEN** an incident whose run is queued and which is then withdrawn
- **WHEN** a worker looks for work
- **THEN** the graph is not invoked for that incident, and its run is settled

### Requirement: Withdrawal is terminal and stamps the end

`withdrawn` SHALL be a terminal status, distinct from `resolved` and from
`escalated`: the incident ended because a human took it, not because Argus
fixed it and not because Argus ran out of moves. The incident SHALL record the
time it was withdrawn as the time it ended.

#### Scenario: A withdrawn incident reports itself finished

- **GIVEN** a withdrawn incident
- **WHEN** anything asks whether it has ended
- **THEN** it is reported as ended, and its end time is the moment it was
  withdrawn

#### Scenario: Withdrawn is not resolved

- **GIVEN** a withdrawn incident
- **WHEN** its outcome is read
- **THEN** it is distinguishable from an incident Argus resolved and from one
  Argus escalated

### Requirement: The timeline says what was withdrawn and what was undone

The system SHALL record on the incident's timeline that it was withdrawn, what
Argus had done by that point, and one entry per undo step attempted, each saying
whether the state was put back or was found already changed by somebody else. A
human reading a withdrawn incident SHALL be able to tell what state Argus left
behind without inspecting the environment.

#### Scenario: An undo that succeeded is narrated

- **GIVEN** a withdrawn incident in which Argus had changed a flag
- **WHEN** the incident's timeline is read
- **THEN** it records the change Argus made and that the flag was put back

#### Scenario: An undo that found an outside change is narrated

- **GIVEN** a withdrawn incident in which Argus had changed a flag that somebody
  then changed again
- **WHEN** the incident's timeline is read
- **THEN** it records that the flag was left as found because it no longer held
  what Argus set

#### Scenario: A withdrawal with nothing to undo says so

- **GIVEN** an incident withdrawn before Argus took any action
- **WHEN** the incident's timeline is read
- **THEN** it records the withdrawal and that nothing had been changed
