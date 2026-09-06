## ADDED Requirements

### Requirement: A withdrawal overrides the status the walk would derive

Where an incident has been withdrawn, the system SHALL keep `withdrawn` as its
status regardless of what the walk's state would otherwise derive, and SHALL NOT
write a transition out of it. Withdrawal is a fact about the incident recorded
from outside; the derivation is a pure function of the walk's state and cannot
see it, so a node returning after a withdrawal would otherwise write the status
its own work implied and quietly revive an incident a human had ended.

#### Scenario: A node returning after a withdrawal does not move the status

- **GIVEN** an incident withdrawn while a node was running
- **WHEN** that node returns work whose derived status is `mitigating`
- **THEN** the incident's status remains `withdrawn`, and no transition to
  `mitigating` is persisted or published

#### Scenario: The derivation itself is unchanged

- **GIVEN** any walk state
- **WHEN** its status is derived
- **THEN** the derivation performs no I/O and never returns `withdrawn`, which
  is set only by the withdrawal itself
