## ADDED Requirements

### Requirement: Rolling back answers output-quality degradation
The strategy registry SHALL map `output-quality-degradation` to the deployment
rollback, as it maps a bad deployment and a config-induced failure: a revision
that made the answers worse is undone by returning to the one that answered well.

#### Scenario: The mode maps to the rollback strategy
- **GIVEN** a hypothesis determining output-quality degradation
- **WHEN** a mitigation is proposed for it
- **THEN** a deployment rollback is proposed
