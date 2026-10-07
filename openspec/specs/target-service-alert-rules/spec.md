# target-service-alert-rules Specification

## Purpose
TBD - created by archiving change the-alert-decides-whether-a-mitigation-held. Update Purpose after archive.
## Requirements
### Requirement: The shop's alert rules are evaluated, and their state is readable
The Target Service SHALL hold its alert rules - each with a query range, a group evaluation
interval, a keep-firing-for period and a condition over its own generated metrics - and SHALL
evaluate each rule's state when asked, over the minutes its range covers ending at the most
recent evaluation the rule's interval allows, judged by the wall clock so it follows the
simulated clock.

#### Scenario: A rule fires and resolves
- **GIVEN** a scenario whose metrics cross a rule's condition and later fall back
- **WHEN** the rule's state is read through both changes
- **THEN** it reads firing, then normal

#### Scenario: A frozen window still resolves
- **GIVEN** a scenario whose window froze after the fix
- **WHEN** the rule's state is read
- **THEN** it is evaluated over the window's last minutes, not over minutes with no data

### Requirement: The rule is readable in Grafana's shape
The Target Service SHALL answer `GET /api/v1/provisioning/alert-rules/{uid}` with the rule's
`data[].relativeTimeRange`, `for` and `keep_firing_for`, the rule-group route with its
`interval`, and `GET /api/prometheus/grafana/api/v1/rules?rule_uid=` with its current state,
`health` and `lastEvaluation`.

#### Scenario: Argus reads a rule
- **WHEN** the rule-definition, rule-group and rule-state routes are asked for a rule
- **THEN** they answer with the fields Argus reads, in Grafana's field names

### Requirement: The alerts the shop sends name their rule
Every alert the Target Service sends SHALL name the rule it is about where Grafana's webhook
does: in `generatorURL`, as `<root>/alerting/grafana/<uid>/view`, with no field of its own.

#### Scenario: A raised alert names its rule
- **WHEN** the shop raises an alert for a scenario
- **THEN** the alert's `generatorURL` links to the rule uid whose state routes answer for it

### Requirement: Existing scenarios' rules fit the fixture's clean minutes
Every existing scenario's rule SHALL resolve within the clean minutes the fixture shows
after its fix.

#### Scenario: A reverted flag resolves inside the frozen window
- **WHEN** the flag scenario's flag is turned off
- **THEN** its rule reads normal before the window freezes

### Requirement: A rule definition carries its query and its comparator
The rule-definition route SHALL carry, in Grafana's shape, the PromQL query each
series rule evaluates as its data query's `model.expr` - a query the shop's
Prometheus stand-in answers - and the comparator its threshold applies as the
threshold expression's evaluator `type`.

#### Scenario: A definition names a query the stand-in answers
- **WHEN** any series rule's definition is read and its `model.expr` is sent to
  the Prometheus stand-in
- **THEN** the stand-in answers it with the series the rule is evaluated over

### Requirement: A rule may fire below its threshold
A rule SHALL be able to fire when its reduced value is below its threshold as
well as above it, and its definition SHALL carry `lt` for the former as it
carries `gt` for the latter.

#### Scenario: A share that falls fires a below rule
- **GIVEN** a rule `lt 0.8` over a share that falls to 0.4 and stays there past
  the rule's pending period
- **WHEN** the rule's state is read
- **THEN** it reads firing

