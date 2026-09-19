## MODIFIED Requirements

### Requirement: The metrics summary identifies anomalous minutes
The system SHALL return bucket values that distinguish anomalous minutes from
baseline ones for each pre-seeded scenario, so a caller can select which
buckets to drill into. Every bucket SHALL carry the resource fields alongside
the rate and latency ones, so that a fault whose first signal is resource use
is visible in the same summary as one whose first signal is errors.

#### Scenario: The feature-flag-toggle scenario shows an error-rate spike
- **GIVEN** the `feature-flag-toggle` scenario is active
- **WHEN** `get_metrics_summary` is called
- **THEN** the buckets after the flag is toggled report a materially higher
  error rate than those before it

#### Scenario: The bad-deployment scenario shows a latency spike
- **GIVEN** the `bad-deployment` scenario is active
- **WHEN** `get_metrics_summary` is called
- **THEN** the buckets after the deploy report a materially higher p95 latency
  than those before it

#### Scenario: The memory-leak scenario shows a climb rather than a step
- **GIVEN** the memory-leak scenario is active
- **WHEN** `get_metrics_summary` is called
- **THEN** each bucket reports higher `memory_used_bytes` than the one before
  it, and no single bucket is far above its predecessor

#### Scenario: Every bucket carries resource usage whatever the scenario
- **GIVEN** any active scenario
- **WHEN** `get_metrics_summary` is called
- **THEN** every bucket carries `memory_used_bytes` and
  `process_start_time_seconds` alongside its rate and latency fields
