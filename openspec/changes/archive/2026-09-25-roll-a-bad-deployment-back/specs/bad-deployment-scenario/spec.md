## ADDED Requirements

### Requirement: The regression is real code on the path every request takes
The Target Service SHALL carry, at the revision this scenario deploys, a
lifetime average spend computed by walking the shopper's purchases once per
purchase instead of from the total the account already carries. The figure SHALL
be identical to the one the revision before it produced - what changed is only
what it costs - and it SHALL sit on the always-on path rather than behind a
rollout, so that every request pays it.

That path rather than the guarded figures, for a reason the code forces: the
rollout guards select between the three figures in order, so a revision that
shipped a guarded figure to everyone would make the monthly summary unreachable
and take the fault out of the flag scenarios that depend on it. The always-on
figure can be made slow while leaving every other scenario exactly as it was.

#### Scenario: The slow path is in the source, not in the generator
- **GIVEN** the repository at the revision this scenario deploys
- **WHEN** the lifetime average's rendering is read
- **THEN** it recomputes the total from the purchases once per purchase, where
  the revision before it divides the carried total once

#### Scenario: The figure does not change, only its cost
- **GIVEN** a shopper's history
- **WHEN** the lifetime average is rendered at each of the two revisions
- **THEN** both produce the same figure

#### Scenario: No other scenario's telemetry moves
- **GIVEN** the revision this scenario deploys
- **WHEN** any other scenario is seeded and a window retrieved
- **THEN** its figures are what they were, because what a page costs is computed
  from the staged scenario and not from how the source happens to be written

#### Scenario: No flag moved
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** the window's flag changes are retrieved
- **THEN** there are none, so nothing but the deploy accounts for the onset

### Requirement: A deploy is the only record of what changed
The Target Service SHALL record the deploy that staged the incident in its
deploy history alone. No log line SHALL mention a deployment, a version or a
release, so that a diagnosis of a bad deployment can only have been reached by
retrieving the deploy history - which is the property this scenario exists to
demonstrate, and the one a scenario whose logs name the deploy cannot.

#### Scenario: The logs do not mention the deploy
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** the window's log lines are retrieved
- **THEN** none of them names a deployment, a version or a release

#### Scenario: The history holds the revision running and the one before it
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** the deploy history is retrieved
- **THEN** it holds the revision the application is running and the revision
  deployed before it, so that a rollback has somewhere to go

### Requirement: The incident is visible everywhere and attributable in one place
The Target Service SHALL compute a minute's telemetry from which revision is
deployed. While the slower revision is running, the median, the 95th and the 99th
percentiles SHALL all depart their baseline together and by the same multiple -
every request pays the cost, so nothing hides - while the error rate and memory
SHALL stay at their baselines. Nothing fails and nothing is given up on: an
incident where requests time out is a different incident, and one whose error
rate moved would be diagnosable without reading the deploy history at all.

This is what makes it the mirror of the three scenarios that hide: detection is
trivial here and attribution is the whole difficulty, because the deploy history
is the only evidence naming a cause.

#### Scenario: Every percentile departs and the heap does not
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** a window spanning the onset is retrieved
- **THEN** `p50_ms`, `p95_ms` and `p99_ms` all depart their baseline and
  `memory_used_bytes` does not

#### Scenario: Nothing fails
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** a window spanning the onset is retrieved
- **THEN** the error rate is at its baseline throughout

#### Scenario: The pages that return are correct
- **GIVEN** a seeded bad-deployment scenario
- **WHEN** an account page is served and returns
- **THEN** the figures on it are the ones the shopper's purchases support

### Requirement: A platform rollback ends the incident
The Target Service SHALL treat a rollback to the earlier revision as ending the
slow stretch, at the moment it is performed, and SHALL keep those minutes in the
window rather than erasing them - the minutes the shop spent slow are what
happened, and a window that lost them when somebody mitigated would take the
incident out of the record exactly when the mitigation wants judging against it.

#### Scenario: The stretch ends when the rollback is performed
- **GIVEN** a seeded bad-deployment scenario whose window shows the departure
- **WHEN** the application is rolled back to the earlier revision
- **THEN** the slow stretch is recorded as ended at that moment, and the window
  still shows the minutes before it

#### Scenario: Recovery is observable after the rollback
- **GIVEN** a rolled-back bad-deployment scenario
- **WHEN** a window is retrieved once the shop has settled
- **THEN** the percentiles have returned to their baseline

### Requirement: The rollback mitigates without resolving
The Target Service SHALL leave the slower revision in the repository when it is
rolled back. The incident SHALL therefore remain open for a fix, and the fix
SHALL be a change to the service's source - which is what distinguishes this
from a configuration that was changed into a broken state, where what remains to
be fixed is a values file.

#### Scenario: The repository still holds the regression
- **GIVEN** a rolled-back bad-deployment scenario
- **WHEN** the repository's own branch is read
- **THEN** it still holds the slower rendering path

#### Scenario: Reconciliation would bring it back
- **GIVEN** a rolled-back bad-deployment scenario
- **WHEN** automated sync is re-enabled
- **THEN** the slower revision is deployed again
