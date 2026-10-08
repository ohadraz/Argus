# accelerator-pinning-mitigation Specification

## Purpose
How Argus answers a replica placed on the wrong card: by holding the alerting
service's deployment to the one card its pre-onset pods ran on, worked out from
the recorded placement and never from a read made when acting, admitted as a
drain, and put back - selector and reconciliation both - by a withdrawal.
## Requirements
### Requirement: Accelerator heterogeneity is answered by a pin to an accelerator
The system SHALL answer `accelerator-heterogeneity` by pinning the alerting
service's deployment to one accelerator. Pinning sets the deployment's node
selector on the accelerator label, so every replica is scheduled onto nodes that
carry that accelerator.

#### Scenario: The mode maps to the pin
- **GIVEN** a hypothesis determining accelerator heterogeneity, and a recorded
  placement that names one good accelerator and a different suspect
- **WHEN** a mitigation is proposed
- **THEN** it is a pin of the alerting service to the good accelerator

### Requirement: The accelerator to pin to comes from the recorded placement and the onset
The system SHALL classify the recorded placement's pods against the onset it was
recorded with. A pod that started earlier than one minute before the onset is a
pre-onset pod. Any other pod started at the onset.

The good accelerators SHALL be those of the pre-onset pods, and the suspect
accelerators those of the pods that started at the onset.

A pin SHALL be proposed only where there is exactly one good accelerator and at
least one suspect, and no suspect is also good. In every other case no action
SHALL be proposed, and the walk SHALL go on as for any candidate no action
answers. That covers:
- a suspect that is also good;
- no pod started at the onset;
- more than one good accelerator;
- a pod with no accelerator;
- no recorded placement.

#### Scenario: A replica moved at the onset
- **GIVEN** two pods that started hours before the onset on V100 nodes, and one
  that started thirty seconds before the onset on an A100 node
- **WHEN** a mitigation is proposed
- **THEN** it pins to V100

#### Scenario: The suspect is also on a good replica
- **GIVEN** pre-onset pods on V100 and A100, and an onset pod on A100
- **WHEN** a mitigation is proposed
- **THEN** none is proposed

#### Scenario: Nothing started at the onset
- **GIVEN** a recorded placement whose pods all started before the onset
- **WHEN** a mitigation is proposed
- **THEN** none is proposed

#### Scenario: An unlabelled node
- **GIVEN** a recorded placement in which some pod's accelerator is absent
- **WHEN** a mitigation is proposed
- **THEN** none is proposed

### Requirement: A pin to an accelerator is a generic mitigation
The pin SHALL belong to the declared set of generic mitigations and be taken
without approval. It is a drain, a mitigation in Google SRE's generic set: it moves
traffic off a class of hardware without changing what is deployed. It SHALL be
reversible: its undo descriptor SHALL record the selector value the deployment
had before, or that it had none.

#### Scenario: A pin proceeds without approval
- **GIVEN** a proposed pin of the alerting service to an accelerator
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, and the action is announced and recorded

### Requirement: Automated sync is suspended for the pin and restored by the undo
The write tier SHALL suspend the application's automated sync before patching the
live deployment, where it was on, and SHALL record that it did. The undo SHALL put
the selector back as it was, removing it where there was none, and only then put
automated sync back, where the pin suspended it.

#### Scenario: Pin and undo round trip
- **GIVEN** an application syncing itself, with no accelerator selector
- **WHEN** it is pinned and the pin is undone
- **THEN** the selector is gone and automated sync is on again

### Requirement: A pin already in force is not repeated
The write tier SHALL report a pin as exhausted, and change nothing, where the
deployment is already pinned to the accelerator asked for.

#### Scenario: Pinned twice
- **GIVEN** a deployment already pinned to V100
- **WHEN** a pin to V100 is asked for
- **THEN** it is reported exhausted and no patch is sent

### Requirement: A pin mitigates without resolving
A pin that the alert confirms SHALL leave the incident mitigated, not resolved:
the deployment is held off the suspect accelerator, and the code that answers
differently there is unchanged, so a fix is proposed.

#### Scenario: The pin held
- **GIVEN** a pin after which the paging rule reads normal
- **WHEN** the walk ends
- **THEN** the incident is mitigated and a fix was proposed

