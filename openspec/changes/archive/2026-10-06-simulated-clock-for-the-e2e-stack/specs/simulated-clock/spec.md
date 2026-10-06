## ADDED Requirements

### Requirement: Argus reads one clock, which a stack may run faster than real time
Every reading of the current instant in Argus's runtime path SHALL come from
`argus_core`'s clock. Given an epoch and a speed, that clock SHALL read
`epoch + (real - epoch) * speed`; given neither, it SHALL read the real clock.

#### Scenario: No simulated clock configured
- **WHEN** a process starts with no epoch and no speed set
- **THEN** the clock reads the real time

#### Scenario: A simulated clock configured
- **WHEN** a process starts with an epoch and a speed of 10, and 3 real seconds pass
- **THEN** the clock has moved 30 seconds

#### Scenario: Stamps come from the same clock
- **WHEN** an incident event or a replay-log entry is created without an explicit time
- **THEN** its time is the clock's reading, not the real time

### Requirement: A wait measured in the stack's time costs its share of real time
Mitigation's re-reads and arrival polls SHALL be measured in the clock's seconds,
because they stand for time passing in the world being watched, so that at speed
`k` each lasts `1/k` of its length in real time. A wait that bounds real work
(an HTTP timeout, the investigation's budget, a poll for a queue) SHALL stay real.

#### Scenario: Mitigation's re-read at speed 10
- **WHEN** Mitigation waits its ten seconds between metric reads on a clock running at 10
- **THEN** one real second passes

#### Scenario: A lease measured by Postgres on the stack's clock
- **WHEN** the worker holds a run whose lease Postgres measures on a clock running at `k`
- **THEN** the lease is renewed `k` times as often in real time, and the run is never reclaimed while it is being walked

### Requirement: Every party of an e2e stack reads the same clock
Every party of an e2e stack SHALL read the clock Argus reads - Argus's Postgres,
the flag provider, the flag provider's database and the Target Service - to within
a few simulated seconds, for the whole run.

#### Scenario: Readings taken together
- **WHEN** each party's clock is read at once during a run at speed 10
- **THEN** every reading is within a few simulated seconds of Argus's own

#### Scenario: Two databases stamp one walk
- **WHEN** Argus reverts a flag during an incident
- **THEN** the provider's database stamps that change between the action Argus's database recorded and the incident's end

### Requirement: The replayed e2e session runs on a simulated clock
`e2e_replay` SHALL start its stack with an epoch of the session's start and a
speed above 1, handed to every service and to the pytest process alike. Every
other session SHALL run on the real clock - `e2e` included, because a real model's
answer takes real seconds that a faster clock turns into minutes.

#### Scenario: A replayed case on the simulated clock
- **WHEN** `e2e_replay` runs a case that waits out a verification window
- **THEN** the case passes on the existing recordings and takes a fraction of its real-clock time
