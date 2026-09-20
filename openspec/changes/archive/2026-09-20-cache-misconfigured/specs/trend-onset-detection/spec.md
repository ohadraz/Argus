## ADDED Requirements

### Requirement: The median is one of the signals an onset is found in
The system SHALL treat a departure in `p50_ms` as marking a minute anomalous,
alongside `error_rate`, `p95_ms` and `memory_used_bytes`. A fault that removes a
fast path leaves the tail describing what it already described - the slow
requests - while moving what a typical request costs by an order of magnitude.
An incident of that shape is invisible in the tail and plain in the median, so a
system reading only the tail would not find it at all.

#### Scenario: A departing median marks a minute anomalous
- **GIVEN** a window whose `p50_ms` climbs steeply while `p95_ms`, `error_rate`
  and `memory_used_bytes` stay flat
- **WHEN** the buckets are classified
- **THEN** the minutes after the climb begins are anomalous

#### Scenario: Recovery is judged on the median too
- **GIVEN** an incident found on the median alone
- **WHEN** the service is asked whether it has recovered
- **THEN** the median returning to its baseline is what answers, rather than a
  tail that never left it

### Requirement: A quantile's departure is judged against its own spread
The system SHALL judge each latency quantile's departure against the spread of
that quantile's own baseline, so that a series which is quiet in absolute terms
but noisy relative to its level is not read as departing on its noise. The
median and the tail sit at different magnitudes on the same service, and a bar
set in shared absolute terms would be strict for one and permissive for the
other.

#### Scenario: A noisy series does not depart on its noise alone
- **GIVEN** a window in which `p50_ms` wobbles around a low baseline and
  nothing has happened
- **WHEN** the buckets are classified
- **THEN** no minute is anomalous
