## MODIFIED Requirements

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
