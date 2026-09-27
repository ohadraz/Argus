## ADDED Requirements

### Requirement: The load outgrows the capacity the deployment was sized for
The Target Service SHALL stage a scenario in which the traffic it reports climbs
from its baseline to several times it and then holds, while nothing about the
service itself changes. No source is faulty, no configuration is wrong, no flag
moved and nothing was deployed: the deployment is running the replica count it
was sized with, and that count was correct for the load of the day before.

The climb SHALL be a ramp rather than a step, because what makes this mode hard
is that it arrives gradually enough for the service to look merely busy first.

#### Scenario: Reported volume climbs and then holds
- **GIVEN** a staged demand-saturation scenario
- **WHEN** a metrics window is read
- **THEN** `request_volume` rises across the early minutes and then stays at its
  elevated level

#### Scenario: Nothing about the service changed
- **WHEN** the deploy history, the flag history and the service's own source are
  read for the window
- **THEN** no deployment landed, no flag moved, and the source is the same
  revision that served the quiet minutes

### Requirement: Utilisation pins at capacity while latency goes on climbing
The Target Service SHALL compute CPU demand for a minute from the traffic it
served against the capacity its live replica count provides, and SHALL report
`cpu_used_cores` clamped at `cpu_limit_cores` - a service cannot use more CPU
than it has. The latency a minute reports SHALL be derived from *demand* over
capacity, which is not clamped, so requests keep getting slower after the gauge
has stopped rising.

The median, the 95th and the 99th SHALL climb together, because every request
queues for the same exhausted resource. The error rate SHALL stay at its
baseline, and memory SHALL stay at its own: errors are the leak's late signal,
and a saturated heap is the leak's signal entirely, so a scenario that borrowed
either would blur the one distinction it exists to draw.

#### Scenario: The gauge sits at the ceiling
- **GIVEN** a window over the saturated minutes
- **WHEN** the buckets are read
- **THEN** `cpu_used_cores` equals `cpu_limit_cores` in each of them

#### Scenario: Latency separates two saturated minutes the gauge cannot
- **GIVEN** two saturated minutes whose reported volumes differ
- **WHEN** the buckets are read
- **THEN** both report the same `cpu_used_cores` and the busier one reports
  higher latency

#### Scenario: The quantiles move and the error rate does not
- **WHEN** a window covering the incident is read
- **THEN** `p50_ms`, `p95_ms` and `p99_ms` have all climbed from their baselines,
  and `error_rate` and `memory_used_bytes` are both where they were

### Requirement: The scenario's live condition is the deployment's replica count
The Target Service SHALL compute each minute's telemetry from the replica count
that was in force **during that minute**, and SHALL expose the count as state the
deployment platform's scaling operation changes - so the scenario reacts to
whoever scales it, the demo console or Argus, exactly as the flag scenarios react
to whoever moves the flag.

The count SHALL therefore be recorded as a history of resizes rather than as a
single value, for the reason the serving process's restarts are: a minute already
served was served at the size the deployment had then, and a value that moved
would regenerate the saturated minutes at the size the deployment reached
afterwards - erasing the stretch the mitigation wants to be judged against at the
moment it is performed.

Raising the count SHALL bring utilisation below the level at which requests
queue, and latency SHALL return to its baseline in the minutes that follow. A
scenario whose telemetry could not react would be one no mitigation could be
honestly graded against.

#### Scenario: Scaling out ends the incident whoever asks
- **GIVEN** a staged demand-saturation scenario whose latency has climbed
- **WHEN** the replica count is raised, by the console or by Argus
- **THEN** `cpu_used_cores` falls below `cpu_limit_cores` and latency returns to
  its baseline in the following minutes

#### Scenario: Scaling out does not quieten the minutes already served
- **GIVEN** a staged demand-saturation scenario whose latency has climbed
- **WHEN** the replica count is raised and the whole window is read again
- **THEN** the minutes before the resize still report the saturated capacity and
  the climbed latency they were served at

#### Scenario: Putting the count back returns the service to saturation
- **GIVEN** a scaled-out deployment whose latency has recovered
- **WHEN** the replica count is set back to what it was
- **THEN** utilisation pins at capacity again and latency climbs again

### Requirement: A restart is refuted rather than accidentally right
The Target Service SHALL leave this scenario's telemetry unchanged by a restart,
beyond the process start time the restart moves. Demand and capacity are both
where they were, so the service is saturated again from its first served minute -
which is what makes the wrong answer to this incident measurably wrong.

This is the property the split between the two halves of resource exhaustion
rests on. A scenario a restart quietened would be one in which naming it a leak
cost nothing.

#### Scenario: Restarting changes nothing but the start time
- **GIVEN** a staged demand-saturation scenario whose latency has climbed
- **WHEN** the service is restarted and the following minutes are read
- **THEN** `process_start_time_seconds` has changed, and latency and utilisation
  are where they were

#### Scenario: A mitigation taken on a leak is refuted and put back
- **GIVEN** a walk that diagnosed a resource leak here and restarted the service
- **WHEN** the outcome is judged
- **THEN** the hypothesis is refuted, and the walk moves on to another candidate

### Requirement: Reverting a flag is not an answer here, and no flag is offered as one
The Target Service SHALL stage no flag for this scenario and SHALL NOT name one
as the thing that breaks it, for the reason a leak, an upstream failure and a bad
deployment name none: a page offering a flag to watch would be offering a control
that changes nothing, and naming one would point at a suspect the fixture
invented.

#### Scenario: The scenario stages no flag
- **GIVEN** a staged demand-saturation scenario
- **WHEN** the flag history for the window is read
- **THEN** no flag change appears in it

#### Scenario: Moving a flag changes nothing
- **GIVEN** a staged demand-saturation scenario
- **WHEN** any flag is moved and the following minutes are read
- **THEN** the telemetry is unaffected
