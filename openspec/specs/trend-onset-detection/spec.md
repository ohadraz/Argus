# trend-onset-detection Specification

## Purpose
Dating a fault that ramps rather than steps. A baseline taken from the
window's quietest minutes cannot find the start of a climb, so the window's
earliest minutes furnish a second baseline and the earlier onset wins - and a
climb that fills the whole window asks for a wider one. Resource usage joins
error rate and latency as a signal an onset is found in.
## Requirements

### Requirement: A fault that ramps is dated where the climb began
The system SHALL locate the onset of a metric that rises gradually at the first
minute of the rise, not at the minute the value happens to become extreme. A
baseline taken from the window's lowest half by value cannot do this: on a ramp
that half is the early part of the climb, so the baseline rises with the fault
and the spread derived from it is the slope rather than the noise. The system
SHALL therefore also derive a baseline from the window's **earliest** minutes in
time order, and SHALL report as the onset whichever of the two baselines finds
the earlier one.

The value-ordered baseline SHALL be retained rather than replaced. It is what
keeps a window containing an older, already-resolved incident from dating the
current one from that, and the two answer different questions: one asks what is
unusual for this service, the other asks when this window stopped looking like
its own beginning.

#### Scenario: A ramp is dated at its start, not its peak
- **GIVEN** a window whose first third is steady and whose remaining minutes
  climb continuously to several times the steady value
- **WHEN** the onset is located
- **THEN** the onset is a minute at the start of the climb, not one near the
  window's end

#### Scenario: A step change is dated where it already was
- **GIVEN** a window that is flat and then jumps to a sustained higher value
- **WHEN** the onset is located
- **THEN** the onset is the first minute of the higher value, unchanged from
  what the value-ordered baseline alone reported

#### Scenario: An earlier resolved incident does not become the onset
- **GIVEN** a window containing a brief departure that recovered, followed by
  calm, followed by the current departure
- **WHEN** the onset is located
- **THEN** the onset is the current departure's first minute, not the earlier
  one's

### Requirement: A climb older than the window asks to be widened
The system SHALL report that a window has no visible start whenever its earliest
minutes are themselves already part of the departure, including when the
departure is a gradual climb rather than a step. A ramp that fills the whole
window is the case this exists for: every minute is slightly worse than the one
before, no minute looks like a departure from its neighbours, and the system
would otherwise report a confident onset from the middle of a fault that began
before anything retrievable.

#### Scenario: A window filled entirely by a climb is flagged as having no start
- **GIVEN** a window in which every minute is higher than the one before it,
  from the first minute to the last
- **WHEN** the buckets are classified
- **THEN** the earliest bucket is anomalous, so the onset is reported as a lower
  bound and the window is widened on the next round

#### Scenario: A climb that begins inside the window is not flagged
- **GIVEN** a window whose first third is steady before a climb begins
- **WHEN** the buckets are classified
- **THEN** the earliest bucket is not anomalous and the window is not widened

### Requirement: Resource usage is one of the signals an onset is found in
The system SHALL treat a departure in `memory_used_bytes` as marking a minute
anomalous, alongside `error_rate` and `p95_ms`. A leak's earliest and clearest
signal is memory, and it precedes the latency and errors it eventually causes -
so a system that read only the consequences would date every leak at the moment
it became a user-visible failure.

#### Scenario: Climbing memory marks a minute anomalous before latency moves
- **GIVEN** a window whose `memory_used_bytes` climbs steadily while `p95_ms`
  and `error_rate` stay flat
- **WHEN** the buckets are classified
- **THEN** the minutes in the climb are anomalous

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
