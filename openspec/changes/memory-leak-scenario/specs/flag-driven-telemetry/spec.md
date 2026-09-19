## ADDED Requirements

### Requirement: Every generated bucket reports resource usage
The Target Service SHALL report `memory_used_bytes`, `memory_limit_bytes` and
`process_start_time_seconds` on every metric bucket it generates, whatever
scenario is staged and whether or not one is. A field that appears only during
the scenario that needs it would be a field a reader learns to treat as a
signal by its presence rather than by its value, and a baseline nobody can see
is not a baseline.

#### Scenario: A calm service reports steady resource usage
- **GIVEN** no scenario is staged
- **WHEN** `GET /metrics` is requested
- **THEN** every bucket reports memory near a steady baseline, well under its
  limit, and an unchanging process start time

#### Scenario: The flag scenario's resource usage stays flat
- **GIVEN** the flag has been on for several minutes
- **WHEN** `GET /metrics` is requested
- **THEN** the affected buckets show an elevated error rate and memory within
  its normal range

## MODIFIED Requirements

### Requirement: The error rate rises while latency stays flat
The Target Service SHALL keep the flag-caused failure mode distinguishable from
a deployment-caused one and from a resource-caused one: while the flag is on,
the error rate SHALL depart from baseline, and the latency percentiles and the
resource fields SHALL NOT. Three failure modes that moved the same metrics
would be three scenarios a reader can only tell apart by being told which is
staged.

#### Scenario: The three failure modes stay distinguishable
- **GIVEN** the flag has been on for several minutes
- **WHEN** `GET /metrics` is requested
- **THEN** the affected buckets show an elevated error rate, with latency
  percentiles and memory within their normal ranges
