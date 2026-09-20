# memory-leak-scenario Specification

## Purpose
The resource-leak scenario the Target Service stages: a real accumulation in
its own source, telemetry computed from how long the process has been up so a
restart reclaims it and the climb resumes, logs that name the condition, and a
restart control reachable by whoever asks. Graded on the repository's own test
suite passing against a fix - never on the telemetry going quiet, which is the
property the scenario exists to demonstrate.
## Requirements

### Requirement: The leak is a real accumulation in the service's own source
The Target Service SHALL carry a fault that genuinely accumulates as requests
are served - state retained per request and never released - rather than a
scripted metric that merely rises. The fault SHALL be present in the source at
the seeded commit, SHALL be uncovered by the repository's own test suite, and
SHALL be reachable by reading the code, so that the fix is a real change to real
code and the test that exposes it is a real test.

#### Scenario: The seeded commit is green despite the fault
- **GIVEN** the repository at its seeded commit
- **WHEN** its test suite runs
- **THEN** it passes, because no test covers the accumulation

#### Scenario: A fix arrives with the test that exposes it
- **GIVEN** a proposed fix on its own branch
- **WHEN** the repository's test suite runs against that branch and against the
  seeded commit
- **THEN** the new test fails at the seeded commit and passes on the branch

### Requirement: The leak's telemetry climbs from the last restart
The Target Service SHALL compute resource usage for a minute from how long the
process has been running rather than from a fixed script, so that memory climbs
continuously while the service stays up, returns to its baseline the moment it
restarts, and climbs again afterwards - because the leak is still in the code.
Latency SHALL follow memory as the limit is approached, and the error rate SHALL
rise only once the service is failing, so that the three signals depart in the
order a real leak makes them depart.

#### Scenario: Memory climbs while the service stays up
- **GIVEN** a service running with the leak, not restarted
- **WHEN** a metrics window is read
- **THEN** `memory_used_bytes` is higher in each minute than in the one before

#### Scenario: A restart reclaims the memory and the clock starts again
- **GIVEN** a service whose memory has climbed
- **WHEN** it is restarted and a metrics window is read
- **THEN** memory returns to its baseline, `process_start_time_seconds`
  changes, and memory begins climbing again from that minute

#### Scenario: Latency follows memory rather than moving with it
- **GIVEN** a window covering the early part of a climb
- **WHEN** the buckets are read
- **THEN** memory has departed from its baseline and latency has not yet

### Requirement: The leak's logs name what is happening
The Target Service SHALL emit log lines that describe the resource condition in
the words a real service uses - the heap approaching its limit, and the
termination and restart when it reaches it - so that a reader who found the
incident through metrics can confirm it through logs, and so that the logs alone
identify the fault as a leak rather than as a slow dependency.

#### Scenario: The logs report the heap approaching its limit
- **GIVEN** a window in which memory has climbed past a warning level
- **WHEN** the log lines for that window are read
- **THEN** they report the heap's size against its limit

#### Scenario: A restart is recorded in the logs as well as the metrics
- **GIVEN** a service that restarted after exhausting its memory
- **WHEN** the log lines covering that minute are read
- **THEN** they record the termination and the start that followed it

### Requirement: The scenario is restarted through a control, and graded on the fix
The Target Service SHALL expose, under its scenario-control prefix, a restart
that reclaims the leaked memory - the live condition this scenario reacts to,
in place of the flag the others use. A flag is not the condition for this
scenario, because a flag flipped hours before the alert falls outside every
window a reader retrieves and is not what causes a leak.

The scenario SHALL be graded as the bug scenarios are: resolved means the
repository's own test suite passes against the proposed fix's branch. It SHALL
NOT be gradable by the telemetry going quiet, because a restart quiets the
telemetry without fixing anything, which is the property the scenario exists to
demonstrate.

#### Scenario: Restarting reclaims the memory whoever asks
- **GIVEN** a staged leak whose memory has climbed
- **WHEN** the restart control is called, by the demo console or by Argus
- **THEN** memory returns to baseline and the scenario continues to climb from
  there

#### Scenario: A restart does not mark the scenario resolved
- **GIVEN** a staged leak that has been restarted and whose telemetry is calm
- **WHEN** the scenario is graded
- **THEN** it is not resolved, because the repository's test suite has not been
  shown to pass against a fix
