## MODIFIED Requirements

### Requirement: Automated sync is suspended for the scale and restored by the undo
The system SHALL suspend the platform's automated reconciliation of the
application before scaling it, and SHALL record whether reconciliation was in
force as it was found. A GitOps controller reverts a live replica count at its
next sync, back to what the repository holds - so a scale-out taken under
automated sync is a mitigation with a timer on it, and the service would return
to saturation at a moment nothing in the record explains.

**Reconciliation is one instance of a general rule and not the rule itself.**
Anything that re-derives the state a mitigation just set has to be suspended or
changed before it is set, and a repository is only one such thing: a live
autoscaler owns the replica count too, and re-derives it from its own metric
within a sync period. So a scale-out is not the mitigation for a deployment whose
count an autoscaler is moving, and the system SHALL NOT suspend an autoscaler in
order to make one fit. That is a different mode with a different answer - the
controller is patched rather than worked around - and a scale-out that reached for
it would be one action silently becoming two.

The system SHALL therefore leave a live autoscaler alone, and SHALL let such a
scale-out be refuted like any other action the evidence does not bear out. The
count will be re-derived, the service will not recover, and the walk will move on
- which is the honest outcome for a mitigation aimed at the wrong mode, and is
what a fixture with a live controller in it demonstrates rather than asserts.

The undo SHALL restore two things: the replica count that was running, and the
reconciliation setting as it was found. The setting SHALL never be restored to a
default - an application somebody had already stopped reconciling is left
stopped, because Argus does not turn on a thing it did not turn off.

The undo SHALL restore the count it recorded even where something else has since
moved the live count away from it. The descriptor's job is to leave nothing Argus
set behind, not to leave the deployment at a size Argus can vouch for - and a
count a controller immediately re-derives is a count Argus is no longer
responsible for.

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

#### Scenario: A live autoscaler is not suspended by a scale-out
- **GIVEN** an application whose replica count an autoscaler is moving
- **WHEN** a scale-out is performed
- **THEN** only automated reconciliation is suspended, the autoscaler is left as
  it was found, and the undo descriptor records nothing about it

#### Scenario: A scale-out the controller undoes is refuted
- **GIVEN** a scale-out of an application whose autoscaler re-derives the count
- **WHEN** the service is watched for recovery
- **THEN** the hypothesis is refuted, the recorded count is put back, and the
  walk moves on to another candidate
