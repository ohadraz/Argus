# slow-canary-scenario Specification

## Purpose
The Target Service staging an incident that is below every aggregate but one: a
correct but quadratic rendering path, shipped behind a flag to three percent of
traffic. Nothing fails and nothing else moves, so the median, the p95 and the
error rate all say the shop is well. It is the mirror of the cache
misconfiguration - that incident hides *in* the tail, this one hides behind it -
and the only series it exists in is the 99th percentile.
## Requirements

### Requirement: The shop has a second rendering path that is correct and slow
The Target Service SHALL contain, in its own source, a second way of rendering
the account page's spend figure which returns a correct figure on every input
and costs more the more the shopper has bought. It SHALL be ordinary-looking
code whose cost follows from its shape - a walk of the purchase history repeated
once per item - rather than a deliberate sleep or a marker, so that a correct
fix is a change to the logic.

It SHALL NOT fail. A path that sometimes raised would move the error rate, and
an incident visible in the error rate is not the incident this scenario stages.

#### Scenario: The slow path renders a correct figure for any history
- **GIVEN** any shopper's purchase history the shop holds
- **WHEN** the page is rendered by the slow path
- **THEN** it returns the figure that path is for, and does not raise - so the
  error rate is the one a calm shop reports

#### Scenario: The slow path costs more for a heavier account
- **GIVEN** two shoppers, one with a handful of purchases and one with many
- **WHEN** each page is rendered by the slow path
- **THEN** the second costs proportionally more than the first

### Requirement: The flag ships one feature at a time
The Target Service SHALL route the flag's traffic to exactly one of the features
that flag guards, decided by the scenario staged. A flag that shipped the slow
path and the failing path at once would stage two faults rather than one: the
error rate would move, and the incident this scenario exists to stage - the one
no aggregate but the tail reports - would be visible in the first aggregate
anybody looks at.

This SHALL hold for every request of every minute, not only for the requests the
rollout reached. The cohort is a small share of the sample; the choice of what
the flag ships is a property of the scenario, and applying it only to the cohort
leaves the rest of the flag's traffic on the other feature.

Suppressing the other feature SHALL NOT change what any other scenario reports.
Each minute seeds one generator, so the draw that decides the other feature's
cohort is still taken and its result discarded.

#### Scenario: Staging the slow rollout ships no failing path
- **GIVEN** the scenario staged, with its flag on
- **WHEN** the window's telemetry is generated
- **THEN** no minute's error rate departs from the shop's idle, and no log line
  reports the other feature's failure

#### Scenario: The four scenarios that ship the other feature are unchanged
- **GIVEN** a scenario that stages the flag without the rollout
- **WHEN** its telemetry is generated
- **THEN** every figure it reports is the one it reported before the slow
  feature existed

### Requirement: The rollout reaches an exact small share of each minute's traffic
The Target Service SHALL route an exact count of each minute's sampled requests
to the slow path while the scenario's flag is on - `round(share × sample)`,
scaled by how much of the minute the flag was on for - rather than deciding each
request by a draw.

The share SHALL sit between one in a hundred and five in a hundred. Above five
the 95th percentile moves and the incident becomes an ordinary latency
regression; below one the 99th percentile cannot see it either and there is
nothing left to detect.

The count SHALL be exact rather than drawn because at these shares a draw over a
sample of this size lands outside that band often enough to matter: a scenario
whose whole claim is that the p95 never sees this cannot be wrong about it one
minute in twenty-five.

#### Scenario: A whole minute with the flag on
- **GIVEN** a minute over which the rollout was live throughout
- **WHEN** that minute's telemetry is generated
- **THEN** exactly the configured share of the sample took the slow path

#### Scenario: The minute the rollout began in
- **GIVEN** a minute over which the rollout was live for half the elapsed
  seconds
- **WHEN** that minute's telemetry is generated
- **THEN** half as many requests took the slow path, so the onset is a slope
  rather than a step

#### Scenario: A minute with the flag off
- **GIVEN** a minute before the rollout began
- **WHEN** that minute's telemetry is generated
- **THEN** no request took the slow path

### Requirement: The incident is visible in the tail and in nothing else
The Target Service SHALL generate, for this scenario, telemetry in which
`error_rate`, `p50_ms`, `p95_ms` and `memory_used_bytes` are indistinguishable
across the onset, while `p99_ms` departs by a multiple of its baseline. That is
the scenario: every aggregate a monitoring stack watches most confidently is one
this incident does not appear in.

The shop SHALL consult a healthy cache throughout, because the mixture of a
cached path and a recomputed one is what puts the 95th percentile on a
recomputed page - and a p95 already describing a recomputed page is the
mechanism by which it does not move when a few pages become much slower.

#### Scenario: The aggregates do not move
- **GIVEN** a window spanning the rollout's onset
- **WHEN** its buckets are read
- **THEN** no minute's `error_rate`, `p50_ms`, `p95_ms` or `memory_used_bytes`
  departs from the window's quiet stretch

#### Scenario: The tail moves unmistakably
- **GIVEN** the same window
- **WHEN** its buckets are read
- **THEN** every minute after the onset reports a `p99_ms` several times the
  baseline, and every minute before it reports the baseline

#### Scenario: The cache is answering throughout
- **GIVEN** any minute of the scenario, before or after the onset
- **WHEN** its bucket is read
- **THEN** `cache_hit_ratio` is at the shop's healthy level, unchanged across
  the onset

### Requirement: The alert names the percentile that moved
The Target Service's monitoring SHALL raise this scenario's alert against the
99th percentile, naming it in the summary a responder reads. A rule written
against the 95th percentile - which is how most latency alerting is written -
SHALL NOT be what fires, because it would not fire on this at all.

#### Scenario: Staging the scenario pages somebody about the tail
- **WHEN** the scenario is seeded and the alert fires
- **THEN** the alert's summary names the 99th percentile rather than the 95th or
  the error rate

### Requirement: Putting the rollout back ends the incident
The Target Service SHALL end this scenario's condition when the flag is returned
to its resting state, by whoever returns it, exactly as the other generated flag
scenarios do. The tail SHALL fall back to its baseline from that minute and stay
there.

The incident is therefore mitigated and resolved together: nothing is left in
the code that a new process would find, and nothing is left in a file that a
platform would re-apply. That distinguishes it from the leak and the
misconfiguration, and it is why the mitigation that answers it is one that
already exists.

#### Scenario: The flag is put back
- **GIVEN** the scenario running with its flag on
- **WHEN** anything returns the flag to its resting state
- **THEN** the minutes from then on report the baseline tail, and the scenario
  settles rather than continuing

#### Scenario: Nothing else ends it
- **GIVEN** the scenario running with its flag on
- **WHEN** the serving process is restarted
- **THEN** the tail is unchanged, because what makes the pages slow is a rollout
  rather than anything the process accumulated
