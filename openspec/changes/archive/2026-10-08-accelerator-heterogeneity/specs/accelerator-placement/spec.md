## ADDED Requirements

### Requirement: The platform says where each replica runs
The deployment platform's read port SHALL offer the placement of an application's
pods: for each pod, its name, the node it runs on, the accelerator that node
carries, and when the pod started. The accelerator SHALL be absent where the
platform does not say which one the node carries, and never guessed. Only the
vendor's adapter SHALL know where these are read from.

#### Scenario: Each pod's node and accelerator are read
- **GIVEN** a platform whose resource tree lists three pods, each naming its node,
  and whose hosts carry an accelerator label
- **WHEN** the placement is read
- **THEN** three placements come back, each with its node, that node's
  accelerator and the pod's start time

#### Scenario: A node with no accelerator label
- **GIVEN** a pod whose node carries no accelerator label
- **WHEN** the placement is read
- **THEN** that pod's placement names its node and no accelerator

### Requirement: The read tier exposes the placement
The read server SHALL expose a tool that returns the alerting service's placement,
and the typed read client SHALL expose it as a function returning Argus's own
placement values.

#### Scenario: The client returns placements
- **WHEN** the client asks for a service's placement
- **THEN** it receives a list of placements, not the platform's response

### Requirement: The placement is recorded with the onset before anything is done
The Investigator SHALL read the placement once per round, after the onset is
measured and before the model's first turn. It SHALL publish the placement with
that onset as an event and return it on its findings. The walk SHALL decide an
action from that recorded placement and never from a read made when acting.

A placement that could not be read SHALL be published as an unanswered retrieval
and carried as absent. It SHALL NOT be carried as an empty placement.

#### Scenario: The placement is on the timeline before the first action
- **GIVEN** an incident whose service's placement is readable
- **WHEN** the walk takes its first action
- **THEN** an event carrying the placement and the onset was published before it

#### Scenario: An unreadable placement
- **GIVEN** a platform that will not answer the placement read
- **WHEN** the Investigator reads it
- **THEN** an unanswered retrieval is published, and the findings carry no
  placement

### Requirement: The model is shown the placement
The opening message SHALL show the model each pod's node, accelerator and start
time, and SHALL say which pods started at or after the onset.

#### Scenario: A pod that started at the onset is marked
- **GIVEN** a recorded placement in which one pod started within a minute before
  the onset
- **WHEN** the opening message is built
- **THEN** that pod is shown as having started at the onset

### Requirement: The placement is said in words
The narration SHALL render the placement event as one line naming each pod's
accelerator, and the pods that started at the onset.

#### Scenario: The timeline names the moved replica
- **WHEN** a placement event in which one pod started at the onset on a different
  accelerator is narrated
- **THEN** the line names that pod and its accelerator
