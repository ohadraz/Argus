# output-quality-degradation-scenario Specification

## Purpose
TBD - created by archiving change output-quality-degradation. Update Purpose after archive.
## Requirements
### Requirement: The shop stages a categoriser model upgrade that degrades its output
The Target Service SHALL offer a scenario, `categoriser-model-upgraded`, in which a deployed
revision upgrades the purchase categoriser from model v1 to model v2, and v2's preprocessing
does not match what it was built for, so that most purchases are filed under "General". Every
page SHALL still return 200 at the latency it had before, and the error rate, every latency
quantile, the heap and the CPU SHALL stay flat.

#### Scenario: Only the categoriser's output moves
- **GIVEN** the scenario is seeded
- **WHEN** its window is read
- **THEN** the share of purchases categorised confidently falls from its calm level after the
  onset, and no fixed signal departs

### Requirement: The shop publishes the categoriser's confidence and a rule pages on it
The Target Service SHALL expose `categoriser_confident_ratio` in its Prometheus exposition and
answer `avg(categoriser_confident_ratio)` through its range-query stand-in, and SHALL hold a
rule over that query that fires when the share stays below its threshold, whose definition
carries the query and an `lt` threshold in Grafana's shape.

#### Scenario: The rule fires on the upgrade and resolves on the rollback
- **GIVEN** the scenario is seeded and its onset has passed the rule's pending period
- **WHEN** the rule's state is read, then the deployment is rolled back and the rule's range
  and keep-firing period pass
- **THEN** it reads firing, then normal

### Requirement: The upgrade is a deployed revision Argus can read and roll back
The scenario's deployed revision and its parent SHALL be a commit pair on an unmerged
`deploy/*` branch whose diff is the model version moving from v1 to v2, dated in the
deployment history at the onset, so that the change channel names it and a rollback ends it.

#### Scenario: The change channel names the upgrade
- **GIVEN** the scenario is seeded
- **WHEN** the deployment history and the revision's diff are read
- **THEN** the revision deployed at the onset is the one that moved the model from v1 to v2

### Requirement: The fault Code-Fix fixes is on main and uncovered
v2's preprocessing fault SHALL exist on the demo app's `main`, and no test in `tests/io_shop`
SHALL exercise it, so that `tests/io_shop` is green at head and a fix's own test fails against
`main`.

#### Scenario: The shop's own suite is green with the fault in place
- **WHEN** `tests/io_shop` runs on `main`
- **THEN** it passes

