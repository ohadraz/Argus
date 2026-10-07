## ADDED Requirements

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
