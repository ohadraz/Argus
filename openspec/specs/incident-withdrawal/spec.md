# incident-withdrawal

## Purpose
The one ending Argus does not decide. A human takes the incident back, and
everything Argus was doing about it stops - reachable from every phase the walk
passes through, because the moment somebody wants it back is not one Argus gets
to choose. Like a resolution a person reports, it is recorded with who made it
and through which channel, and the status derivation never returns it: it is
written from outside the walk, and the walk finds out by reading the incident
back.

Marking and stopping are separate, and that separation is what keeps one writer
on an incident. The endpoint only writes the status; the walk asks before each
node whether the incident is still wanted, stops where it is not, and puts back
what it changed itself - conditionally, since a person who withdrew an incident
may already have changed the subject by hand.
## Requirements
### Requirement: A live incident can be withdrawn

The system SHALL allow a live incident to be withdrawn, meaning a human has
taken it back and Argus is to stop working on it. Withdrawal SHALL be accepted
for any non-terminal incident and SHALL be refused for a terminal one, so that
withdrawal cannot undo a mitigation that is confirmed and holding the service
up. Withdrawing an already-withdrawn incident SHALL be accepted and change
nothing further.

The withdrawal SHALL record who withdrew the incident and the channel it came
through. From the Argus UI that is "demo user". From Slack it is the person
who confirmed the offer, with their message as the note.

#### Scenario: A running incident is withdrawn

- **GIVEN** an incident that has not reached a terminal status
- **WHEN** it is withdrawn from the Argus UI
- **THEN** its status becomes `withdrawn`, and its timeline records that "demo
  user" withdrew it from the Argus UI

#### Scenario: A running incident is withdrawn from Slack

- **GIVEN** an incident that has not reached a terminal status
- **WHEN** a person confirms a withdrawal offer in its Slack thread
- **THEN** its status becomes `withdrawn`, and its timeline records that the
  person withdrew it from Slack, with their words

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
boundary - before a node runs and again when it returns - before every model
turn of the Investigator and of Code-Fix, immediately before every change Argus
makes to the world (a mitigation, a branch, a pull request), and on every pass
of the loop that waits for a service to recover, and SHALL stop rather than
begin its next step. A model call already in flight SHALL be allowed to return,
and its answer SHALL NOT be acted on.

The walk SHALL NOT propose an action, take an action, investigate a further
round, open a pull request, or write a postmortem for a withdrawn incident.

A step that stops because its incident was withdrawn SHALL be reported as
stopped: not as a failed run, not as an investigation that found nothing, and
not as an escalation. Putting back a change Argus itself made is not a step in
this sense and SHALL complete.

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

#### Scenario: An investigation stops between turns

- **GIVEN** an investigation that has asked the model at least once
- **WHEN** the incident is withdrawn before its next turn
- **THEN** the model is not asked again, no hypothesis is recorded, and the walk
  ends without escalating and without recording a failed run

#### Scenario: Code-Fix stops between turns

- **GIVEN** Code-Fix reading the repository with the model
- **WHEN** the incident is withdrawn before its next turn
- **THEN** the model is not asked again, no branch is written, no pull request
  is opened, and no fix attempt is reported

#### Scenario: A fix found after the withdrawal is not proposed

- **GIVEN** Code-Fix whose model has submitted a fix
- **WHEN** the incident was withdrawn before the branch is written
- **THEN** no branch is written and no pull request is opened

#### Scenario: An action is not applied after the withdrawal

- **GIVEN** a mitigation about to apply its action
- **WHEN** the incident has been withdrawn since its node began
- **THEN** the action is not applied, nothing is recorded as needing to be put
  back, and the walk ends

#### Scenario: A refuted change is still put back

- **GIVEN** an action Argus applied that its verification refuted
- **WHEN** the incident is withdrawn while that change is being put back
- **THEN** the change is put back regardless

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
whether the state was put back, was found already changed by somebody else, or
needed no putting back. A human reading a withdrawn incident SHALL be able to tell
what state Argus left behind without inspecting the environment.

The third case arrives with the first action whose change is a removal. Discarding
a cache entry leaves nothing to restore - the entry was a copy of data that never
moved, and the service has already rebuilt whichever copies anybody has asked for -
so a withdrawal there makes no write and must say that it made none. A timeline
silent about it would read as an undo that was skipped.

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

#### Scenario: An action that needed no undo is narrated as such

- **GIVEN** a withdrawn incident in which Argus had discarded cache entries
- **WHEN** the incident's timeline is read
- **THEN** it records the discard, that nothing was written back, and that the
  entries the service needed have been rebuilt from data that never changed

