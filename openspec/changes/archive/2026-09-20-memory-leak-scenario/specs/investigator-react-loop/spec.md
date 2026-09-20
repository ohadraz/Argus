## MODIFIED Requirements

### Requirement: A minute is anomalous relative to the window's own baseline
The system SHALL classify a metric bucket by comparing it against the calm
stretch of the same window, not against an absolute configured value. A bucket
SHALL be anomalous when its `error_rate`, its `p95_ms` or its
`memory_used_bytes` sits further from that baseline than the configured number
of the baseline's own deviations. The baseline's spread SHALL be measured
against the calm stretch's own worst minutes rather than its average deviation,
which reads as zero whenever a metric takes few distinct values - a sampled
error rate is quantised into steps, so most quiet minutes report the identical
figure however much the rate moves, and a spread derived from their average
collapses the threshold onto the baseline.

The calm stretch SHALL be identified two ways, and a bucket SHALL be anomalous
under either. Ordered by value, the window's lowest half is the calm stretch -
which is what keeps an older, already-resolved departure in the same window from
being mistaken for the current one. Ordered by time, the window's earliest
minutes are the calm stretch - which is what makes a gradual climb detectable at
all, since a value-ordered calm half of a ramp is the early ramp, and a spread
derived from it is the slope rather than the noise.

The classification SHALL be made in code rather than by asking the model, and
the same buckets SHALL yield the same classification on every run.

#### Scenario: A minute that leaves the baseline is anomalous
- **GIVEN** a window whose buckets sit at a steady error rate before rising
- **WHEN** the buckets are classified
- **THEN** the earliest bucket that departs from the steady rate is anomalous,
  and the steady ones before it are not

#### Scenario: A quiet stretch whose minutes read alike still has a spread
- **GIVEN** a window whose calm minutes report only a couple of distinct values,
  most of them identical, and which later carries a real departure
- **WHEN** the buckets are classified
- **THEN** the calm minutes are not anomalous, and the departure is

#### Scenario: A gradual climb departs from the window's earliest minutes
- **GIVEN** a window whose first third is steady and whose remaining minutes
  climb continuously, no one of them far above the minute before it
- **WHEN** the buckets are classified
- **THEN** the minutes from the start of the climb onwards are anomalous

#### Scenario: Climbing memory alone marks a bucket anomalous
- **GIVEN** a window whose `memory_used_bytes` departs from its baseline while
  its `error_rate` and `p95_ms` stay steady
- **WHEN** the buckets are classified
- **THEN** the departing bucket is anomalous

### Requirement: An onset is a departure that persisted
The system SHALL take as the onset the first minute of a run of consecutive
anomalous minutes lasting at least the configured number of minutes, rather
than any single anomalous minute. An incident is a state the service remains
in, so it is still present the minute after it began, where a measurement that
departs alone has already recovered by then - and anchoring retrieval on one of
those aims every window, and every widening, at a minute in which nothing
happened. A run still in progress when the window ends SHALL count as an onset
however short it is, since an incident that began a minute ago has not failed
to persist.

Where the two calm stretches disagree about when the run began, the system SHALL
report the earlier of the two onsets. A ramp is dated from where the climb
started, not from the minute the value happened to become extreme, because every
window derived from the onset - the logs read, the changes considered, the money
counted - is otherwise aimed after the fault began.

#### Scenario: A lone departed minute is not an onset
- **GIVEN** a window in which one minute departs from the baseline and the
  minutes around it do not
- **WHEN** the onset is located
- **THEN** no onset is reported

#### Scenario: A departure still going at the window's end is an onset
- **GIVEN** a window whose final minute departs from the baseline, with no later
  minute yet recorded
- **WHEN** the onset is located
- **THEN** that minute is reported as the onset

#### Scenario: The same shape is anomalous at any scale
- **GIVEN** two windows with the same shape of departure, one around a low
  steady error rate and one around a high steady error rate
- **WHEN** the buckets of each are classified
- **THEN** the departing bucket is anomalous in both

#### Scenario: Elevated latency alone marks a bucket anomalous
- **GIVEN** a window whose `p95_ms` departs from its baseline while its
  `error_rate` stays steady
- **WHEN** the buckets are classified
- **THEN** the departing bucket is anomalous

#### Scenario: A window with no calm stretch has no visible baseline
- **GIVEN** a window whose earliest bucket is already elevated
- **WHEN** the buckets are classified
- **THEN** the earliest bucket is anomalous, indicating the incident began
  before the window and the onset found in it is only a lower bound

#### Scenario: A ramp is dated at its start rather than near its peak
- **GIVEN** a window that is steady for its first third and then climbs
  continuously to several times the steady value
- **WHEN** the onset is located
- **THEN** the onset is at the start of the climb, not in the last part of the
  window

#### Scenario: A window filled entirely by a climb has no visible start
- **GIVEN** a window in which every minute is higher than the one before it,
  from the first to the last
- **WHEN** the buckets are classified
- **THEN** the earliest bucket is anomalous, so the onset is a lower bound and
  the next round widens the window
