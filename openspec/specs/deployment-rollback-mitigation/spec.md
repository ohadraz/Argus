# deployment-rollback-mitigation Specification

## Purpose
Returning a deployment to the revision it was running before: the failure modes
that call for it, the tool that performs it through the platform's own rollback
rather than by writing to a repository, and what such a change leaves behind for
a withdrawal to put back. One revision carries the code and the configuration it
shipped with, so one action answers a bad deployment and a configuration changed
into a broken state alike. It mitigates and does not resolve - the repository
still holds what caused the incident.
## Requirements

### Requirement: A config-induced failure is a failure mode of its own
The system SHALL carry a failure mode for a deployment's configuration having
been changed into a broken state, distinct from a bad deployment and from a
feature flag being toggled. What distinguishes it is what a reader of the
incident is being told: nothing in the code changed and nothing the configuration
points at is unwell, which is a different account of the incident from new code
having shipped, and a different fix afterwards - a values file rather than the
service's source.

The mapping from modes to mitigations SHALL be many-to-one. A mode is a
classification of what broke, and the strategy registry is a lookup over it, so
two modes MAY be answered by the same action where the same action is what helps:
a bad deployment and a broken configuration are both mitigated by returning the
deployment to the revision it ran before. The choice of mitigation SHALL NOT be
the test of whether a mode may exist.

#### Scenario: The mode maps to the rollback strategy
- **GIVEN** a hypothesis determining a config-induced failure
- **WHEN** a mitigation is proposed for it
- **THEN** a deployment rollback is proposed

#### Scenario: A bad deployment maps to the same strategy
- **GIVEN** a hypothesis determining a bad deployment
- **WHEN** a mitigation is proposed for it
- **THEN** a deployment rollback is proposed, the same action the config-induced
  failure is answered by

#### Scenario: A mode nothing answers is still refused in its own words
- **GIVEN** a hypothesis determining a mode no strategy answers
- **WHEN** the gate is asked
- **THEN** it refuses on the grounds that nothing in the set answers the mode,
  unchanged by this mode's arrival

### Requirement: Rolling a deployment back is a mitigation Argus can take
The system SHALL offer, on the write tier, a tool that rolls a deployment back
to a previously-deployed revision, performed through the deployment platform's
own rollback operation rather than by writing to the configuration repository.
The revision rolled back to SHALL be one the platform already deployed, so that
the change Argus makes is the replaying of a reviewed revision and never the
authoring of a new one. Committing to, merging into or otherwise writing the
configuration repository SHALL NOT be part of this mitigation.

The action, the tool and the undo descriptor SHALL be named for the deployment
they return rather than for the configuration, because one revision carries both
the code and the configuration it was deployed with, and the same call answers a
bad deployment and a broken configuration alike. A name saying "configuration"
would make the sentence a human reads about a rolled-back code deploy false.

#### Scenario: The rollback is performed through the platform's own operation
- **GIVEN** a proposed deployment rollback
- **WHEN** it is performed
- **THEN** the platform's own rollback operation is called, rather than the
  configuration repository being written to

#### Scenario: What is said names the deployment
- **GIVEN** a performed rollback, whatever mode it answered
- **WHEN** the action is narrated
- **THEN** it is said as the deployment having been returned to the revision it
  ran before, and never as a configuration having been rolled back

#### Scenario: No commit is written
- **WHEN** a deployment rollback is performed
- **THEN** no branch, commit or pull request is created in the configuration
  repository

#### Scenario: An application with no earlier entry cannot be rolled back
- **GIVEN** an application whose deployment history holds only the revision it
  is running
- **WHEN** a rollback is attempted
- **THEN** it is refused before anything is changed, and no mitigation is
  recorded as taken

### Requirement: The revision to return to is the platform's to resolve
The system SHALL name only the application when proposing a rollback, and the
tier performing it SHALL resolve which revision to return to - the immediately
preceding deployment. Nothing above the write tier holds a deployment history
to choose from: a strategy reads a hypothesis, the recorded flag changes and a
service name, so an action naming a revision would be naming one nothing could
have read. A commit found in a diff is not necessarily a revision this
application ever ran, and rolling onto one would be shipping an untested state
under the name of a rollback.

#### Scenario: A proposed rollback names the application and nothing else
- **WHEN** a rollback is proposed for either deployment mode
- **THEN** it carries the application, and carries no revision, history entry
  or undo descriptor

#### Scenario: The entry returned to is the one before the running one
- **GIVEN** an application whose history holds two deployments
- **WHEN** a rollback is performed
- **THEN** the platform is asked to return to the earlier of the two

### Requirement: The tier reads the application's history and sync policy itself
The system SHALL read, in the tier performing the rollback, both which entry
the application is currently running and whether the platform is reconciling
the application on its own. Neither belongs above the write tier: a change
event is vendor-neutral by construction, and a history identifier and a sync
policy are one platform's vocabulary. A consumer holding them would be a
consumer that had learned which platform answered.

#### Scenario: The running entry and revision are recorded from what was read
- **WHEN** a rollback is performed
- **THEN** the descriptor it returns carries the history entry and the commit
  that were running before it acted

#### Scenario: An application with no sync policy is treated as not reconciling
- **GIVEN** an application whose state declares no automated sync
- **WHEN** a rollback is performed
- **THEN** the sync policy is left untouched, and the descriptor records that
  reconciliation was already off

### Requirement: Automated sync is suspended for the rollback and restored by the undo
The system SHALL suspend the application's automated sync before rolling back,
because a platform that reconciles continuously refuses a rollback while
automated sync is enabled and would re-apply the broken revision as soon as it
resumed. The suspension SHALL be recorded as part of the change, so that undoing
the mitigation restores both the revision the application was on and the sync
setting it had.

#### Scenario: Sync is suspended before the rollback is attempted
- **GIVEN** an application whose automated sync is enabled
- **WHEN** a rollback is performed
- **THEN** automated sync is suspended first, and the rollback follows

#### Scenario: The undo restores the revision and the sync setting together
- **GIVEN** a performed rollback that is later withdrawn or refuted
- **WHEN** it is undone
- **THEN** the application is returned to the revision it was on and its
  automated sync is restored to the state it had

#### Scenario: An application already not auto-syncing is left as it is
- **GIVEN** an application whose automated sync is already disabled
- **WHEN** a rollback is performed and later undone
- **THEN** the undo leaves automated sync disabled rather than enabling it

### Requirement: A rollback mitigates without resolving
The system SHALL treat a confirmed deployment rollback as having mitigated the
incident and not as having resolved it. The repository still holds the change
that caused the incident, so the incident SHALL remain open for a fix, and what
the rollback bought is the service being well while somebody makes one.

What the remaining fix changes SHALL follow from the mode rather than from the
action: a config-induced failure is fixed in the deployment's values file, and a
bad deployment in the service's source. This is the distinction the two modes
carry now that one action answers both.

#### Scenario: A confirmed rollback does not resolve the incident
- **GIVEN** a rollback whose verdict is confirmed
- **WHEN** the incident's status is derived
- **THEN** it is mitigated rather than resolved

#### Scenario: The remaining fix for a configuration fault is a values change
- **GIVEN** a mitigated config-induced failure
- **WHEN** a fix is proposed
- **THEN** it changes the deployment's values file rather than the service's
  source

#### Scenario: The remaining fix for a bad deployment is a source change
- **GIVEN** a mitigated bad deployment
- **WHEN** a fix is proposed
- **THEN** it changes the service's source
