## ADDED Requirements

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
service's process start time, and SHALL judge whether it helped by whether
resource use fell and the service's symptoms eased. The two are separate
questions: a restart that did not happen and a restart that happened and did not
help are different outcomes, and a system that read only the symptoms would
report the first as the second.

#### Scenario: A restart that never landed is distinguished from one that did not help
- **GIVEN** a restart whose call returned without error
- **WHEN** the metrics after it are read and the process start time is unchanged
- **THEN** the outcome recorded is that the restart did not take effect, not
  that it failed to help

#### Scenario: A restart that reclaimed memory and eased the symptoms is confirmed
- **GIVEN** a restart after which the process start time changed, memory
  returned to its baseline and latency eased
- **WHEN** the verdict is measured
- **THEN** the mitigation is confirmed

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
