## ADDED Requirements

### Requirement: A scenario's live condition may belong to a third party
Scenario control SHALL support a scenario whose condition is the state of a
dependency the shop calls rather than anything inside the deployment. Seeding
it SHALL put that dependency into failure and SHALL touch no flag, no deploy
record and no process. Resetting it SHALL return the dependency to answering.

No mitigation SHALL clear the condition: it is not a flag to revert, not a heap
to reclaim and not a deploy to roll back, which is what makes an incident staged
this way gradeable by telemetry alone.

#### Scenario: Seeding fails the dependency and nothing else
- **WHEN** `upstream-dependency-failure` is seeded
- **THEN** the dependency refuses requests, and the flag provider and deploy
  history record no change

#### Scenario: Resetting restores it
- **GIVEN** the scenario is active
- **WHEN** scenario control resets
- **THEN** no scenario is active, and staging any other one finds the
  dependency answering again
