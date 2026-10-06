# alert-decided-verification Specification

## Purpose
TBD - created by archiving change the-alert-decides-whether-a-mitigation-held. Update Purpose after archive.
## Requirements
### Requirement: An action on a series alert is judged by the alert rule's state
Mitigation SHALL confirm an action when the alert rule is normal at an evaluation whose
query range lies wholly after the change was in force, and SHALL refute it when the rule is
still firing at the deadline, for an incident whose alert reports a series
(`claim = series-condition`) and names the rule that fired. Argus's own metrics SHALL NOT reach a verdict
on such an action, and a metrics read that fails SHALL NOT keep the rule from being read.

#### Scenario: The rule resolves after the fix
- **GIVEN** an incident opened by a series alert, and an action after which the rule's
  condition goes false
- **WHEN** the rule is evaluated over a range that starts after the change was in force
- **THEN** the action is confirmed

#### Scenario: A flap keeps the rule firing
- **GIVEN** an action after which the service flaps with irregular gaps, keeping the
  rule's condition true
- **WHEN** the deadline passes
- **THEN** the action is refuted and the walk tries the next candidate

#### Scenario: One unlucky minute does not undo a working fix
- **GIVEN** an action after which one minute reads at the incident's level and the rule's
  condition stays false
- **WHEN** that minute is read
- **THEN** the action is not refuted, and is confirmed when the rule is normal

#### Scenario: A rule that resolved before the action does not confirm it
- **GIVEN** a rule that went normal during the investigation
- **WHEN** the action is taken
- **THEN** only an evaluation whose range starts after the change was in force can confirm
  it

#### Scenario: A window with nothing departed in it does not refute
- **GIVEN** an action whose metrics window shows no departure
- **WHEN** the rule reads normal over a range after the change
- **THEN** the action is confirmed

#### Scenario: Metrics that cannot be read do not stop the rule
- **GIVEN** an action whose metrics cannot be read
- **WHEN** the rule reads normal over a range after the change
- **THEN** the action is confirmed

### Requirement: The deadline is read off the rule
The deadline SHALL be the instant the change was in force plus the rule's query range, plus
one evaluation interval of its group, plus its keep-firing-for period, plus
`metrics_reporting_lag_minutes`. Once the rule has been read, no setting of Argus's own other
than that lag SHALL bound it.

#### Scenario: A five-minute rule evaluated every minute
- **GIVEN** a rule over the last 5 minutes, evaluated every minute, with no keep-firing-for
  period and a reporting lag of 1
- **WHEN** the change is in force at 10:00
- **THEN** the deadline is 10:07

### Requirement: The rule's state is polled, not waited for
Mitigation SHALL read the rule's definition and current state through the read tier, by the
rule identity the alert carried, and SHALL NOT depend on a resolved webhook arriving.

#### Scenario: A resolved notification never arrives
- **GIVEN** a rule that went normal and a resolved webhook that was lost
- **WHEN** Mitigation reads the rule's state
- **THEN** the action is confirmed

### Requirement: An evaluation that measured nothing is not a normal rule
A rule whose last evaluation failed or found no data SHALL be read as unreadable rather than
normal, though Grafana reports its state as inactive.

#### Scenario: A rule whose query failed
- **GIVEN** a rule reported inactive with health `error` or `nodata`
- **WHEN** Mitigation reads it
- **THEN** it is unreadable, and does not confirm the action

### Requirement: Findings keep their own confirmation
For an alert that reports a finding of its own (`claim = own-finding`), Mitigation SHALL
judge the action by the store's receipt, or by readings returning, and SHALL NOT wait for
the rule to resolve.

#### Scenario: A discard on a reconciliation alert
- **GIVEN** an own-finding alert whose check runs weekly
- **WHEN** the discard reports what it removed
- **THEN** the action is confirmed without the rule resolving

### Requirement: The recovered minute is still measured from the metrics
The minute the service came back SHALL still be read off the metrics and recorded with the
verdict; the rule decides the verdict, not the minute.

#### Scenario: A confirmed action records its recovery minute
- **WHEN** an action on a series alert is confirmed
- **THEN** the recorded recovery minute is the metrics' first clear minute, not the time the
  rule resolved

