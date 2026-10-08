## MODIFIED Requirements

### Requirement: Argus reads one clock, which a stack may run faster than real time
Every reading of the current instant in Argus's runtime path SHALL come from
`argus_core`'s clock. Given an epoch and a speed, that clock SHALL read
`epoch + (real - epoch) * speed`; given neither, it SHALL read the real clock.
Telemetry is the exception: it records the process rather than the world being
watched, and the OTel SDK stamps it from the real clock, so the times it is
written and filed under are the real clock's too.

#### Scenario: No simulated clock configured
- **WHEN** a process starts with no epoch and no speed set
- **THEN** the clock reads the real time

#### Scenario: A simulated clock configured
- **WHEN** a process starts with an epoch and a speed of 10, and 3 real seconds pass
- **THEN** the clock has moved 30 seconds

#### Scenario: Stamps come from the same clock
- **WHEN** an incident event or a replay-log entry is created without an explicit time
- **THEN** its time is the clock's reading, not the real time

#### Scenario: Telemetry is on the real clock
- **WHEN** a process on a simulated clock starts its telemetry
- **THEN** its run directory is named for the real time, as its spans are stamped
