# paging-rule-series Specification

## Purpose
TBD - created by archiving change output-quality-degradation. Update Purpose after archive.
## Requirements
### Requirement: The series a rule watches is read from its definition
The read tier SHALL resolve, from the paging rule's Grafana provisioning definition, the one
PromQL query the rule evaluates and the direction its threshold calls worse. It SHALL follow the
rule's `condition` reference through its expressions to the threshold - a `threshold` expression
or a `classic_conditions` one - and from there to the single data query the threshold reads,
taking that query's `model.expr`. A `gt` or `gte` evaluator SHALL read as worse above; an `lt`
or `lte` evaluator SHALL read as worse below.

A definition the read tier cannot resolve this way - a math expression between the query and
the threshold, more than one data query feeding it, a range evaluator, or a query with no
`expr` - SHALL resolve to no series rather than to a guess.

#### Scenario: A threshold rule names its query and direction
- **GIVEN** a rule whose condition is a threshold `lt 0.8` over a reduction of query `A`
  with `expr` `avg(categoriser_confident_ratio)`
- **WHEN** the rule's series is resolved
- **THEN** it is `avg(categoriser_confident_ratio)`, worse below

#### Scenario: A classic condition names its query and direction
- **GIVEN** a rule whose condition is `classic_conditions` with a `gt` evaluator over query `A`
- **WHEN** the rule's series is resolved
- **THEN** it is query `A`'s `expr`, worse above

#### Scenario: A rule this cannot follow resolves to nothing
- **GIVEN** a rule whose threshold reads a math expression over two queries
- **WHEN** the rule's series is resolved
- **THEN** no series is resolved, and nothing is guessed

### Requirement: The metrics window carries the paging rule's series
The read tier's metrics retrieval SHALL take the rule that paged, where the alert named one, and
SHALL carry that rule's series on every minute of the window as a rule reading - the minute's
value and the direction the rule calls worse - beside the fixed fields. Where the alert named no
rule, or the rule's series could not be resolved or fetched, every minute SHALL carry no rule
reading, and the fixed fields SHALL be returned as before.

#### Scenario: A named rule's series is carried
- **GIVEN** an alert naming a rule whose series resolves and is served by Prometheus
- **WHEN** the window is retrieved
- **THEN** each minute carries the rule reading's value for that minute and its direction

#### Scenario: A rule whose series cannot be fetched leaves the fixed window intact
- **GIVEN** an alert naming a rule whose query Prometheus refuses
- **WHEN** the window is retrieved
- **THEN** the fixed fields are returned and no minute carries a rule reading

### Requirement: The paging rule's series is judged in the rule's direction
Where the window carries a rule reading, departure, onset and recovery SHALL judge it as one more
signal beside the five, against the same baseline-relative bar, oriented so that the direction
the rule calls worse is the direction that departs.

#### Scenario: A share that falls departs
- **GIVEN** a window whose fixed signals are flat and whose rule reading, worse below, falls
  from about 0.95 to about 0.4 and stays there
- **WHEN** the onset is found
- **THEN** it is the minute the share began to fall

#### Scenario: A share that rises under a worse-below rule does not depart
- **GIVEN** a rule reading, worse below, that rises above its baseline
- **WHEN** the window is judged
- **THEN** no departure is found in it

