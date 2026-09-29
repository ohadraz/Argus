## ADDED Requirements

### Requirement: A rollback answers a rollout that never converged
The system SHALL map an in-flight compatibility break to the same deployment
rollback that answers a bad deployment and a config-induced failure, and SHALL
add no action, no undo descriptor and no member of the pre-authorised set to do
it.

What the action achieves here differs from what it achieves for the other two,
and the difference SHALL be what the mitigation is said to have done. For a bad
deployment and a broken configuration, going back removes the thing that was
wrong. Here nothing that was deployed is wrong: going back **converges the
fleet**, and it is one version serving rather than the older version serving that
ends the incident.

It follows that the mitigation is indifferent to direction in principle and not
in practice. Converging forward would end the incident equally, and the system
SHALL NOT do so, because completing a rollout cannot be put back - there is no
returning a fleet to half-deployed - and an action that cannot be undone is not
one Argus takes unasked.

#### Scenario: The third mode reaches the rollback
- **GIVEN** an incident determined as an in-flight compatibility break
- **WHEN** a mitigation is selected
- **THEN** the deployment rollback is proposed, by the same strategy that answers
  a bad deployment

The narration SHALL go on saying the action and not the reason. One line serves
all three modes - the deployment was returned to the revision it ran before -
because that is what happened in every one of them, and a line that varied with
the diagnosis would be the record asserting a verdict the action itself does not
carry. Where the three differ is the account the incident gives, which is the
hypothesis's own words and the postmortem's, and that is where the difference
belongs.

#### Scenario: What is said names the action and not a verdict on the revision
- **GIVEN** a rollback performed against an in-flight compatibility break
- **WHEN** the action is narrated
- **THEN** it is said as the deployment having been returned, in the same words a
  rollback against either other mode is said in, and says nothing about a
  revision having been faulty

#### Scenario: Converging forward is not offered
- **GIVEN** an incident determined as an in-flight compatibility break
- **WHEN** the mitigations available for it are enumerated
- **THEN** completing the rollout is not among them
