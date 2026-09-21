## ADDED Requirements

### Requirement: The tail is one of the signals an onset is found in
The system SHALL treat a departure in `p99_ms` as marking a minute anomalous,
alongside `error_rate`, `p50_ms`, `p95_ms` and `memory_used_bytes`. A fault
reaching a small enough share of traffic is below the 95th percentile by
arithmetic, fails nothing and allocates nothing, so every other signal is flat
across its onset by construction. An incident of that shape is invisible in all
four and plain in the tail, and a system reading only the four would find no
onset at all rather than a late one.

Recovery SHALL be judged on the tail too, by the same rule and for the same
reason the median is. An incident found in the tail alone can only be confirmed
as over by the tail coming back down; asking a p95 that never moved whether it
has returned to its baseline confirms a mitigation the instant it is taken.

#### Scenario: A departing tail marks a minute anomalous
- **GIVEN** a window whose `p99_ms` climbs steeply while `p50_ms`, `p95_ms`,
  `error_rate` and `memory_used_bytes` stay flat
- **WHEN** the buckets are classified
- **THEN** the minutes after the climb begins are anomalous

#### Scenario: Recovery is judged on the tail too
- **GIVEN** an incident found on the tail alone
- **WHEN** the service is asked whether it has recovered since a mitigation was
  taken
- **THEN** the tail returning towards its baseline is what answers, rather than
  a p95 that never left it

#### Scenario: A tail that merely tracks its p95 changes nothing
- **GIVEN** a window in which `p99_ms` rises and falls in proportion with
  `p95_ms`
- **WHEN** the buckets are classified
- **THEN** the same minutes are anomalous as when the tail was not read at all

### Requirement: A signal that never departed does not hold recovery open
The system SHALL exclude from the recovery judgement any signal that never
reached the incident's level in the window. Recovery asks how far a series has
fallen back from where the incident put it, and a series the incident never
moved has no such level: the question has no answer, and answering it anyway
means judging a mitigation on a signal that carries no evidence about it.

This matters wherever a fault is invisible in a series by design. A
configuration rollback ends an incident whose error rate never moved at all -
the cache fallback is designed behaviour - so a recovery rule that demanded the
error rate return to quiet was demanding a return from somewhere it had never
been, and refused a mitigation that had genuinely worked.

#### Scenario: A flat signal does not deny a recovery the others confirm
- **GIVEN** an incident found on latency alone, in a window whose `error_rate`
  never departed
- **WHEN** the service is asked whether it has recovered
- **THEN** the error rate contributes nothing to the answer, rather than being
  held to the departure bar and failing it

### Requirement: A baseline's spread is what its quiet minutes range over
The system SHALL measure a baseline's spread as the distance between the
quietest and the least quiet of the minutes it takes to be calm, floored at
twice the finest difference that series distinguishes.

The stretch taken to be calm is the window's lowest half by value, so a quantile
read inside it never looks at an ordinary minute: the 90th percentile of the
lowest half is about the 45th of the whole series, and the distance from there
to the 25th measures nothing a bar has to clear. The range is two-sided and
reaches the calm minutes' own worst, which is what a bar has to clear, and it is
safe from the incident because the incident is not in that half by construction.

The floor is what the range cannot supply on a quantised series. A rate measured
over a couple of hundred requests moves in half-percent steps, so a short calm
stretch ranges over one step or exactly zero, and a departure inside a couple of
steps is a departure the measurement cannot claim to have seen. The resolution
SHALL be read from the calm stretch rather than from the whole window or from a
reported request volume: across a whole window the two nearest distinct values
may be the calm level and the incident's, and a reported volume is not always
the number of requests a rate was measured over.

A stretch of consecutive minutes judged by when it happened rather than by value
is a different shape of evidence and SHALL keep its quantile, because such a
stretch may already be rising and its range is then its own slope - a bar built
from that grows with the climb it exists to date.

#### Scenario: A quantised calm stretch does not set a bar its own minutes clear
- **GIVEN** a window whose error rate is sampled over a couple of hundred
  requests, so most quiet minutes report one of two adjacent figures
- **WHEN** the buckets are classified
- **THEN** no minute is anomalous

#### Scenario: A window that is already climbing when it opens is still dated
- **GIVEN** a window whose opening minutes are themselves part of a climb
- **WHEN** the buckets are classified
- **THEN** the opening's bar is read from how far it sits above its own middle,
  rather than from the slope it is on

### Requirement: Recovery does not credit a run still going at the window's end
The system SHALL require a run of departed minutes to persist for the configured
number of minutes before it denies recovery, and SHALL NOT credit a run with
persistence merely because the window ended while it was going.

An onset is asked of a window that was retrieved; recovery is asked of a window
that is being polled, and grows by a minute each time. Its final minute is
therefore always the freshest sample and always the end of whatever run it is
in, so treating an unfinished run as persistent lets one noisy minute deny a
verdict every minute before it supports - and waiting does not clear it, because
each new last minute is a fresh chance to land noisy. A relapse that is real is
unaffected: it is still departed at the next poll, where it is a run of two.

A stretch in which *no* minute has fallen clear is not this case and SHALL NOT
count as recovery. Every minute since the action still being the incident is the
service not having answered yet, which is absence of evidence rather than
evidence of recovery.

#### Scenario: A noisy final minute does not deny a recovery
- **GIVEN** a window in which the service came back after a mitigation and its
  last minute alone departs again
- **WHEN** the service is asked whether it has recovered since the mitigation
- **THEN** it has

#### Scenario: A service that has not yet answered has not recovered
- **GIVEN** a window in which every minute since the mitigation is still at the
  incident's level
- **WHEN** the service is asked whether it has recovered since the mitigation
- **THEN** it has not
