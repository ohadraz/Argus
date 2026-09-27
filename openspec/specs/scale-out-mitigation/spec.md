# scale-out-mitigation Specification

## Purpose
Answering load that outgrew the capacity a deployment was sized for by
adding capacity it never had: the failure mode that calls for it, the tool
that performs it through the platform's own scaling operation rather than by
writing to a repository, the bound on how far one attempt may go, and what
such a change leaves behind for a withdrawal to put back. It is the one
generic mitigation that restores nothing, and it mitigates without resolving:
the repository still asks for the size that was too small, and the load is
still arriving.
## Requirements

### Requirement: Demand saturation is a failure mode of its own
The system SHALL carry a failure mode for a resource that was sized correctly
meeting load that has since grown, distinct from a resource leak. The two are
the halves of resource exhaustion and they are separated by what the correct
response is: a leak is answered by reclaiming what accumulated, and this is
answered by adding capacity the deployment never had. Since what dispatches on a
mode is the choice of mitigation, they are two modes.

The meaning that travels with the mode into the tool schema SHALL say what
separates it from its nearest neighbours - from a leak, that the consumption
moved *with* the traffic rather than independently of it; and from a bad
deployment and from a dependency's failure, that nothing changed and the time is
spent in the service's own work rather than waiting on somebody else's.

#### Scenario: The mode maps to the scale-out strategy
- **GIVEN** a hypothesis determining demand saturation
- **WHEN** a mitigation is proposed for it
- **THEN** a scale-out is proposed

#### Scenario: A leak and a saturated service reach different mitigations
- **GIVEN** two hypotheses, one determining a resource leak and one determining
  demand saturation
- **WHEN** a mitigation is proposed for each
- **THEN** the first proposes a restart and the second a scale-out

### Requirement: Scaling out is a mitigation Argus can take
The system SHALL offer, on the write tier, a tool that raises a deployment's
replica count, performed through the deployment platform's own scaling operation
rather than by writing to the configuration repository. It SHALL belong to the
declared set of generic mitigations, so it is taken without approval - on the
same ground the other three are, that it is a routine, well-understood procedure
applied before the cause is fully understood.

It SHALL be the first mitigation that adds something rather than restoring
something, and the set's criterion SHALL be unchanged by that: what admits an
action is membership of the set, never whether the change could be put back.

The system SHALL NOT offer the reverse. Capacity is never reduced autonomously,
because being wrong about scaling out costs money and being wrong about scaling
in costs an outage.

#### Scenario: A scale-out proceeds without approval
- **GIVEN** a proposed scale-out of the alerting service's deployment
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, and the action is announced and recorded

#### Scenario: Scaling is performed through the platform, not the repository
- **WHEN** a scale-out is performed
- **THEN** the deployment platform's own scaling operation is called, and no
  commit, branch or pull request is written

### Requirement: The replica count to scale to is the tier's to resolve
The system SHALL NOT carry a target replica count on the proposed action. The
action SHALL name the application alone, and the tier that performs it SHALL
read the count that is running, derive the target from it, and report both back.

A target count is meaningless without the count it replaces; the count it
replaces is live state that only the write tier can read; and an agent naming an
absolute count would be asserting what the deployment is running now - a fact no
evidence in front of it carries, and one that is wrong the moment anybody has
scaled anything.

The count SHALL be read from the platform's live resource rather than from the
repository's configuration. What the repository holds is what the platform is
asked to converge on, which is a different number from the one in force as soon
as one scale-out has happened.

#### Scenario: The action carries no number
- **WHEN** a scale-out is proposed
- **THEN** it names the application and carries no replica count

#### Scenario: Both counts are reported back
- **GIVEN** a deployment running three replicas
- **WHEN** a scale-out is performed
- **THEN** the result says which count was running and which count is running
  now

#### Scenario: A second scale-out doubles what is running, not what git holds
- **GIVEN** a deployment whose repository says three replicas and which a
  previous scale-out left running six
- **WHEN** a scale-out is performed again
- **THEN** the count it replaces is six

### Requirement: Automated sync is suspended for the scale and restored by the undo
The system SHALL suspend the platform's automated reconciliation of the
application before scaling it, and SHALL record whether reconciliation was in
force as it was found. A GitOps controller reverts a live replica count at its
next sync, back to what the repository holds - so a scale-out taken under
automated sync is a mitigation with a timer on it, and the service would return
to saturation at a moment nothing in the record explains.

The undo SHALL therefore restore two things: the replica count that was running,
and the reconciliation setting as it was found. The setting SHALL never be
restored to a default - an application somebody had already stopped reconciling
is left stopped, because Argus does not turn on a thing it did not turn off.

#### Scenario: A scale-out suspends reconciliation first
- **GIVEN** an application the platform reconciles itself
- **WHEN** a scale-out is performed
- **THEN** automated sync is suspended before the count is changed, and the
  undo descriptor records that it had been in force

#### Scenario: An application already not reconciling is left that way
- **GIVEN** an application whose automated sync a human had already suspended
- **WHEN** a scale-out is performed and later undone
- **THEN** the count is put back and automated sync is left suspended

#### Scenario: The undo puts the count back
- **GIVEN** a scale-out that was refuted or an incident that was withdrawn
- **WHEN** the undo runs
- **THEN** the replica count recorded on the descriptor is set again

### Requirement: A scale-out is bounded by how far it may go
The system SHALL bound the replica count a scale-out may reach, and SHALL refuse
to exceed it. The bound SHALL be held by the tier that performs the action, for
the reason the mapping from a service to a workload is held there: it is a fact
about the estate rather than about the incident.

It is a second bound and not the cap. The cap bounds how many times a repeatable
mitigation may be attempted within one incident; this bounds how large any one
attempt may make the deployment. Either alone leaves the other's failure
available - a cap of two with no ceiling permits an unbounded second attempt,
and a ceiling with no cap permits attempts without end below it.

#### Scenario: A scale-out that would exceed the ceiling is clamped
- **GIVEN** a deployment running a count whose double exceeds the ceiling
- **WHEN** a scale-out is performed
- **THEN** the count is raised to the ceiling and the result says so

#### Scenario: A scale-out at the ceiling is refused rather than repeated
- **GIVEN** a deployment already running the ceiling's count
- **WHEN** a scale-out is proposed
- **THEN** it is refused, the refusal names the bound, and the walk moves on to
  another candidate or escalates

### Requirement: A scale-out mitigates without resolving
The system SHALL treat a confirmed scale-out as a mitigation and never as a
resolution. The repository still holds the count the deployment was sized with,
the platform's reconciliation is suspended so that nothing re-applies it, and
the load that outgrew the capacity is still arriving. A withdrawal puts the first
two back, which returns the service to saturation.

No patch closes a shortfall of capacity, and the system SHALL NOT claim
otherwise on the model's behalf. The code tier is asked as it is for every other
mode - "I read the code and found nothing" and "nobody looked" reach the same
human and only one of them would be true - and whatever it answers is recorded
as the answer it is. What the system SHALL NOT do is treat a patch as the
resolution: the incident is mitigated by capacity or it is not mitigated at all,
and a proposal against the service's source neither ends this incident nor
resolves it.

Requiring the agent to *decline* would be a requirement on a model's reading
rather than on this system. An agent aimed by a conclusion that names no file
reads the repository at large, and any repository worth patching has something
in it to patch - so a rule saying "no patch for capacity" fails on the reading
rather than on the behaviour it meant to constrain.

#### Scenario: The incident is reported as mitigated
- **GIVEN** a scale-out whose subsequent minutes show the service well
- **WHEN** the outcome is recorded
- **THEN** the hypothesis is confirmed, the incident is mitigated, and it is not
  reported as resolved

#### Scenario: Withdrawing returns the deployment to where it was found
- **GIVEN** a mitigated incident that a human then withdraws
- **WHEN** the undo runs
- **THEN** the replica count and the reconciliation setting are both put back

#### Scenario: A patch is not what ended the incident
- **GIVEN** an incident whose mode is demand saturation and whose scale-out was
  confirmed
- **WHEN** the code tier is reached and answers, whether with a patch or with
  nothing to change
- **THEN** the answer is recorded as what it is, and the incident stays
  mitigated rather than resolved
