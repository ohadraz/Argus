# resource-metrics Specification

## Purpose
What a metric bucket says about the resources a service is consuming: the
memory it was using, the limit that usage is measured against, and the
instant its serving process began - each named as ordinary monitoring names
it, and each aggregated into a minute by a rule the bucket states.
## Requirements

### Requirement: A metric bucket reports resource usage against its limit
The system SHALL carry, on every metric bucket, the memory the service was using
and the limit it is measured against, as `memory_used_bytes` and
`memory_limit_bytes`. Both SHALL be absolute byte counts rather than a ratio: a
ratio is derivable from the pair, where the pair is not derivable from a ratio,
and forecasting when usage will reach the limit needs both. The names SHALL be
those of metrics that already exist in ordinary monitoring - a working-set gauge
and a configured limit - rather than names invented for this system.

#### Scenario: Usage and limit both reach the model
- **WHEN** a metrics summary is retrieved for a window
- **THEN** every bucket in it carries `memory_used_bytes` and
  `memory_limit_bytes`

#### Scenario: A service with no configured limit still reports usage
- **GIVEN** a deployment that imposes no memory limit
- **WHEN** a metrics summary is retrieved
- **THEN** every bucket carries `memory_used_bytes`, and `memory_limit_bytes` is
  absent rather than reported as zero

### Requirement: A restart is visible in the metrics as a change of start time
The system SHALL carry `process_start_time_seconds` on every metric bucket - the
instant the serving process began, as a gauge. A restart SHALL be recognised as
a change in that value between two buckets, rather than by a counter of
restarts. A counter of restarts is a Kubernetes-specific metric; a process start
time is exposed by every ordinary client library on every orchestrator and on
none, and this system SHALL NOT assume which one is running it.

#### Scenario: Memory falling after a restart is distinguishable from load falling
- **GIVEN** two windows in which `memory_used_bytes` drops sharply, one where
  the process start time changed at that minute and one where it did not
- **WHEN** each is read
- **THEN** the first is recognisable as a restart and the second is not

#### Scenario: A window with no restart reports one unchanging start time
- **GIVEN** a window over a service that has not restarted
- **WHEN** the buckets are read
- **THEN** every bucket reports the same `process_start_time_seconds`

### Requirement: A gauge is aggregated per minute by a stated rule
The system SHALL state, for each resource field, how a minute's single value is
derived from the instants within it, because these are gauges sampled at points
in time where the existing fields are rates and quantiles over the whole minute.
`memory_used_bytes` SHALL be the minute's maximum, because what matters about
memory is the peak that could have breached the limit. `memory_limit_bytes` and
`process_start_time_seconds` SHALL be the minute's last observed value, because
each describes a configuration in force rather than a quantity accumulated.

#### Scenario: A minute containing a spike reports the spike
- **GIVEN** a minute in which memory peaked and then fell back
- **WHEN** the bucket for that minute is produced
- **THEN** `memory_used_bytes` reports the peak, not the average or the final
  reading

#### Scenario: A minute containing a restart reports the new process
- **GIVEN** a minute during which the service restarted
- **WHEN** the bucket for that minute is produced
- **THEN** `process_start_time_seconds` reports the new process's start time

### Requirement: A metric bucket reports how much of its work the cache served
The system SHALL carry, on every metric bucket, the share of lookups served from
cache over that minute, as `cache_hit_ratio`. It SHALL be a ratio rather than a
pair of counts, because unlike memory against its limit there is no threshold to
forecast a crossing of - what a reader asks of it is how much of the work the
cache is carrying, and the ratio answers that directly. It SHALL be reported on
every bucket, whether or not the service is under a cache condition, for the
reason the memory fields are: a field that appears when it matters is a signal
by its presence.

#### Scenario: The hit ratio reaches the model
- **WHEN** a metrics summary is retrieved for a window
- **THEN** every bucket in it carries `cache_hit_ratio`

#### Scenario: A service with no cache reports its absence rather than zero
- **GIVEN** a deployment whose service consults no cache
- **WHEN** a metrics summary is retrieved
- **THEN** `cache_hit_ratio` is absent, rather than reported as zero - which
  would be indistinguishable from a cache that is answering nothing

### Requirement: The hit ratio is aggregated per minute as a share of that minute
The system SHALL derive a minute's `cache_hit_ratio` as the share of that
minute's lookups that were served from cache, rather than as the last observed
value or the mean of finer-grained ratios. It is a rate over the minute, as
`error_rate` is, and averaging ratios computed over unequal numbers of lookups
would weight a quiet instant as heavily as a busy one.

#### Scenario: A minute in which the cache became unreachable partway
- **GIVEN** a minute whose first half was served from cache and whose second
  half was not
- **WHEN** the bucket for that minute is produced
- **THEN** `cache_hit_ratio` reports the share over the whole minute rather than
  the value at its end

### Requirement: A metric bucket reports the tail as well as the median and the p95
The system SHALL carry `p99_ms` on every metric bucket, beside `p50_ms` and
`p95_ms`. It SHALL be reported on every bucket whether or not a scenario is
about the tail, for the reason the memory fields and the hit ratio are: a field
that appears when it matters is a signal by its presence, and a quantile with no
visible baseline is one nothing can be said to have departed from.

Unlike `cache_hit_ratio` it SHALL NOT be nullable. A deployment consulting no
cache genuinely has no hit ratio, where no deployment lacks a 99th percentile of
what it served - so an absent tail would be a missing measurement rather than a
meaningful one, and nothing should be invited to read it as a fact about the
service.

#### Scenario: The tail reaches the model
- **WHEN** a metrics summary is retrieved for a window
- **THEN** every bucket in it carries `p99_ms`

#### Scenario: A service under no tail condition still reports a tail
- **GIVEN** a window over a service whose slow requests are the ordinary ones
- **WHEN** the buckets are read
- **THEN** every bucket carries `p99_ms`, at a level that wobbles around a
  baseline rather than being absent or zero

### Requirement: The tail is a percentile of the minute it describes
The system SHALL derive a minute's `p99_ms` as the 99th percentile of the
requests that minute served, by the same rule its `p50_ms` and `p95_ms` are
derived by - not as a multiple of the p95 and not as the maximum. A tail
computed from another quantile cannot move independently of it, and the whole
reason to report a tail is that it can.

#### Scenario: A minute in which a small share of requests were slow
- **GIVEN** a minute in which three requests in a hundred took twenty times as
  long as the rest
- **WHEN** the bucket for that minute is produced
- **THEN** `p99_ms` describes one of the slow requests while `p50_ms` and
  `p95_ms` describe the others
