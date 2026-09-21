## ADDED Requirements

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
