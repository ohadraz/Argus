## ADDED Requirements

### Requirement: A checkout code path fails while the flag is on
The Target Service SHALL contain a checkout code path guarded by a live flag
evaluation, whose flag-on branch contains a real defect that raises at runtime
for every request routed to it. The defect SHALL be a genuine programming error
in ordinary-looking code, not a deliberate raise, so that a correct patch is a
change to the logic rather than the removal of a marker.

#### Scenario: The flag-on branch raises
- **GIVEN** the flag evaluates true
- **WHEN** a checkout is processed through the flag-on branch
- **THEN** it raises an error rather than returning a result

#### Scenario: The flag-off branch succeeds
- **GIVEN** the flag evaluates false
- **WHEN** a checkout is processed
- **THEN** it returns a result and raises nothing

#### Scenario: Only part of the traffic takes the new branch
- **GIVEN** the flag evaluates true
- **WHEN** a minute's worth of checkouts is processed
- **THEN** a fixed minority of them are routed to the flag-on branch and the
  remainder succeed, so the service reads as degraded rather than as wholly down

### Requirement: Metrics and logs are computed from live flag state at request time
The Target Service SHALL derive `GET /metrics` and `GET /logs` from the current
flag state and the record of when that state changed, computed when the request
arrives, by exercising the real checkout code path. No background task, timer,
or self-directed request traffic SHALL be required for the derived content to
stay current.

#### Scenario: Minutes during which the flag was on read as degraded
- **GIVEN** the flag has been on for several minutes
- **WHEN** `GET /metrics` is requested
- **THEN** the buckets covering those minutes carry an elevated error rate

#### Scenario: Minutes after the flag went off read as healthy
- **GIVEN** the flag was on and has since been turned off
- **WHEN** `GET /metrics` is requested after a further minute has elapsed
- **THEN** the bucket covering that minute carries an error rate at the
  service's healthy baseline

#### Scenario: Recovery needs no re-seeding
- **GIVEN** an incident is in progress
- **WHEN** the flag is turned off and nothing else is done
- **THEN** subsequent reads show recovery, with no call to scenario control and
  no restart

#### Scenario: The failure's own words reach the log
- **GIVEN** the flag is on
- **WHEN** `GET /logs` is requested for a minute in which the flag was on
- **THEN** the returned lines include the error the checkout path actually
  raised

#### Scenario: Log volume stays bounded
- **GIVEN** the flag has been on across many minutes
- **WHEN** `GET /logs` is requested
- **THEN** the number of lines returned per minute is bounded, rather than one
  line per failed request

### Requirement: The error rate rises while latency stays flat
The Target Service SHALL keep the flag-caused failure mode distinguishable from
a deployment-caused one: while the flag is on, the error rate SHALL depart from
baseline and the latency percentiles SHALL NOT.

#### Scenario: The two failure modes stay distinguishable
- **GIVEN** the flag has been on for several minutes
- **WHEN** `GET /metrics` is requested
- **THEN** the affected buckets show an elevated error rate and latency
  percentiles within their normal range

### Requirement: The most recent bucket covers the minute in progress
The Target Service SHALL include the minute currently in progress as the newest
metric bucket, aggregated over the seconds elapsed within it so far, so that a
change in flag state is reflected in the reported error rate before the minute
completes.

#### Scenario: The in-progress bucket reflects a mid-minute revert
- **GIVEN** the flag was on and is turned off part-way through the current
  minute
- **WHEN** `GET /metrics` is requested repeatedly during the remainder of that
  minute
- **THEN** the newest bucket's error rate falls with each read

#### Scenario: The in-progress bucket is present from the first second
- **GIVEN** the current minute has only just begun
- **WHEN** `GET /metrics` is requested
- **THEN** a bucket for the minute in progress is returned

### Requirement: Completed minutes read the same every time
The Target Service SHALL return identical values for any minute that has already
completed, however many times it is read, so that two reads of the same past
minute can be compared. Only the minute in progress SHALL change between reads.

#### Scenario: A past minute is stable across reads
- **GIVEN** `GET /metrics` has been requested
- **WHEN** it is requested again later without any flag change
- **THEN** every bucket for a minute that had already completed carries the same
  values as before

### Requirement: Logs and metrics agree with each other
The Target Service SHALL derive the log lines and the metric buckets for a given
minute from the same generated outcomes, so the two channels cannot disagree
about what happened in that minute.

#### Scenario: A degraded minute appears in both channels
- **GIVEN** a minute during which the flag was on
- **WHEN** both `GET /logs` and `GET /metrics` are requested
- **THEN** that minute carries an elevated error rate in the metrics and failure
  lines in the log, under the same minute identifier
