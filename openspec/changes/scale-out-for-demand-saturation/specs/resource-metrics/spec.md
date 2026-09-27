## ADDED Requirements

### Requirement: A metric bucket reports CPU usage against the capacity it has
The system SHALL carry, on every metric bucket, the CPU the service was using and
the capacity that usage is measured against, as `cpu_used_cores` and
`cpu_limit_cores`. Both SHALL be absolute figures in cores rather than a
utilisation ratio, for the reason memory is a pair: the ratio is derivable from
the pair and the pair is not derivable from the ratio.

`cpu_limit_cores` SHALL be the capacity of the *deployment* - the sum across the
replicas serving it - rather than one replica's limit. That is the level every
other field on the bucket is already at, and it is what makes the pair say what
this signal exists to say: capacity that changes when the deployment is scaled,
so the incident and its mitigation are both visible in the same series.

`cpu_used_cores` SHALL be required and `cpu_limit_cores` SHALL be nullable, for
the reasons already stated for the tail and the memory limit: every process uses
CPU, so an absent figure would be a measurement that went astray rather than a
fact about the service, while a deployment imposing no CPU limit is ordinary and
zero would be indistinguishable from having no CPU at all.

#### Scenario: Usage and capacity both reach the model
- **WHEN** a metrics summary is retrieved for a window
- **THEN** every bucket in it carries `cpu_used_cores` and `cpu_limit_cores`

#### Scenario: A service under no capacity condition still reports usage
- **GIVEN** a window over a service with ample headroom
- **WHEN** the buckets are read
- **THEN** every bucket carries `cpu_used_cores`, at a level that wobbles around
  a baseline rather than being absent or zero

#### Scenario: A deployment with no CPU limit reports its absence rather than zero
- **GIVEN** a deployment that imposes no CPU limit
- **WHEN** a metrics summary is retrieved
- **THEN** every bucket carries `cpu_used_cores`, and `cpu_limit_cores` is absent
  rather than reported as zero

#### Scenario: Scaling the deployment moves the capacity it reports
- **GIVEN** a deployment whose replica count is raised
- **WHEN** the buckets for the following minutes are read
- **THEN** `cpu_limit_cores` reports the larger capacity

### Requirement: CPU is aggregated as the minute's mean, where memory is its peak
The system SHALL derive a minute's `cpu_used_cores` as the mean over that minute,
and SHALL state that this differs deliberately from `memory_used_bytes`, which is
the minute's maximum. A heap's peak is what breaches a limit, and a breach is not
undone by the heap falling back afterwards; a second at full CPU is absorbed by
requests queueing and is what an ordinary busy service does all day. A maximum
here would report every minute as saturated and make saturation undetectable by
making everything look saturated.

`cpu_limit_cores` SHALL be the minute's last observed value, as the memory limit
is, because it describes a capacity in force rather than a quantity accumulated -
so a minute during which the deployment was scaled reports the capacity it ended
with.

#### Scenario: A minute with a brief spike is not reported as saturated
- **GIVEN** a minute in which CPU touched its capacity for a few seconds and sat
  well below it otherwise
- **WHEN** the bucket for that minute is produced
- **THEN** `cpu_used_cores` reports the mean, which is below `cpu_limit_cores`

#### Scenario: A minute containing a scale-out reports the new capacity
- **GIVEN** a minute during which the deployment's replica count was raised
- **WHEN** the bucket for that minute is produced
- **THEN** `cpu_limit_cores` reports the capacity after the change
