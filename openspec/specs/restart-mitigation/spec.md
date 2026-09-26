# restart-mitigation Specification

## Purpose
Restarting the service as a mitigation Argus may take unasked: performed
through the deployment platform's own restart action, recorded with no undo
because it leaves nothing behind, verified in two steps - that it landed and
that it helped - and treated as having mitigated the incident without
resolving the cause.
## Requirements

### Requirement: Restarting the service is a mitigation Argus can take
The system SHALL offer, on the write tier, a tool that restarts the service
named by a hypothesis, and SHALL declare that action's kind a generic
mitigation. The tool SHALL be shaped like the deployment platform's own restart
action rather than as a bespoke endpoint, for the reason the deploy-history
channel is shaped like Argo CD's application API: the adapter maps a real
vendor response, and nothing above it learns a shape invented for this system.

#### Scenario: A restart is performed through the write tier
- **GIVEN** a confirmed hypothesis naming a service whose resource use is
  climbing
- **WHEN** the mitigation is taken
- **THEN** the write tier restarts that service, and the read tier holds no code
  path that could have

#### Scenario: A restart is recorded as a mitigation like any other
- **WHEN** a restart is taken
- **THEN** it is recorded against the incident with its subject and the moment
  it was taken, announced in the incident's conversation, and appears in the
  postmortem's account

### Requirement: A restart records no undo and is not treated as having failed to
The system SHALL record a restart with no undo descriptor, because a restart
changes no persistent state and there is nothing to put back. A refuted restart
SHALL leave nothing behind to unwind, and the walk SHALL move on without
reporting an unwind that failed.

#### Scenario: A restart that did not help is not rolled back
- **GIVEN** a restart whose hypothesis was refuted by the metrics that followed
- **WHEN** the walk moves on to the next candidate
- **THEN** no undo is attempted and the incident's account says the restart had
  nothing to put back

### Requirement: A restart is verified by the reclaim, not only by recovery
The system SHALL confirm a restart took effect by reading back a change in the
process start time **of the service that was restarted**, and SHALL judge
whether it helped by whether the alerting service's symptoms eased - its
resource use, its latency, and whatever else the incident departed on. The two
are separate questions asked of two services when those differ: a restart that
did not happen and a restart that happened and did not help are different
outcomes, and a system that read only the symptoms would report the first as the
second.

The start time SHALL be read per service, so that restarting a dependency cannot
be confirmed by observing the service that was paged.

#### Scenario: A restart that never landed is distinguished from one that did not help
- **GIVEN** a restart whose call returned without error
- **WHEN** the metrics after it are read and the restarted service's process
  start time is unchanged
- **THEN** the outcome recorded is that the restart did not take effect, not
  that it failed to help

#### Scenario: A restart that reclaimed memory and eased the symptoms is confirmed
- **GIVEN** a restart after which the restarted service's process start time
  changed, memory returned to its baseline and latency eased
- **WHEN** the verdict is measured
- **THEN** the mitigation is confirmed

#### Scenario: A dependency's restart is confirmed against that dependency
- **GIVEN** a restart addressed to a service other than the one the alert names
- **WHEN** the restart is confirmed
- **THEN** the process start time read is the restarted service's, and an
  unmoved start time on the alerting service does not report the restart as
  having failed

### Requirement: A confirmed restart mitigates without resolving
The system SHALL treat a confirmed restart as having mitigated the incident and
SHALL NOT treat it as having resolved the cause. The walk SHALL go on to look
for a permanent fix, and the incident SHALL end mitigated rather than resolved
even when every symptom has eased.

This is what both industry frames say about a workaround: the service is
restored, and what remains is a documented cause with no fix yet. Restarting a
leaking process is the textbook example.

#### Scenario: A confirmed restart leads to the search for a fix
- **GIVEN** a restart that was confirmed by the metrics that followed
- **WHEN** the walk continues
- **THEN** it proceeds to look for a permanent fix rather than closing the
  incident

#### Scenario: The incident ends mitigated, not resolved
- **GIVEN** an incident mitigated by a restart, with a fix proposed for review
- **WHEN** the walk ends
- **THEN** the incident's final status is mitigated, and its account says the
  cause is still present in the deployed code

### Requirement: What the platform restarts is derived from the service being restarted
The system SHALL derive the resource the platform is asked to restart from the
service the action addresses, and SHALL NOT hold one resource name configured
for the whole estate. A restart addressed to a service other than the one the
alert names SHALL reach that service's resource, not the alerting service's.

A configured single name was correct while the environment held one service, and
is the shape that would silently restart the wrong thing the moment it held two.

#### Scenario: Two services restart their own resources
- **GIVEN** an estate of two services
- **WHEN** each is restarted in turn
- **THEN** each call names that service's own resource
