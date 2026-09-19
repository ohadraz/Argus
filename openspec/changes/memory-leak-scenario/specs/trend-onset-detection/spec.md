## ADDED Requirements

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
