## ADDED Requirements

### Requirement: The investigating phase runs a bounded iterative loop
The system SHALL run investigation as an iterative loop rather than a single
pass. Each iteration SHALL query the metrics summary, locate the onset, read
log lines for a window anchored on that onset, and produce a hypothesis with a
confidence. The loop SHALL exit as soon as a hypothesis reaches the configured
mitigate threshold, and SHALL run no more than the configured maximum number of
iterations.

#### Scenario: A confident first iteration exits immediately
- **GIVEN** an incident whose first iteration produces a hypothesis at or above
  the mitigate threshold
- **WHEN** the Investigator investigates
- **THEN** it returns that hypothesis and performs no further iterations

#### Scenario: The iteration budget is never exceeded
- **GIVEN** an incident where no iteration ever reaches the mitigate threshold
- **WHEN** the Investigator investigates
- **THEN** it performs exactly the configured maximum number of iterations and
  no more

### Requirement: Log retrieval each iteration is anchored on the metric onset
The system SHALL derive the onset from the metrics summary - the earliest
anomalous bucket within the window - and SHALL request log lines for a window
starting before that onset, so that a change event preceding the first
anomalous minute is retrievable.

#### Scenario: The window starts before the onset
- **GIVEN** a metrics summary whose earliest anomalous bucket is at some minute
- **WHEN** the Investigator retrieves log lines for that iteration
- **THEN** the requested window starts strictly before that minute

#### Scenario: No anomalous bucket means no onset to anchor on
- **GIVEN** a metrics summary in which no bucket is anomalous
- **WHEN** the Investigator investigates
- **THEN** it does not report a determined cause, and does not fabricate an
  onset

### Requirement: A minute is anomalous relative to the window's own baseline
The system SHALL classify a metric bucket by comparing it against the calm
stretch of the same window, not against an absolute configured value. A bucket
SHALL be anomalous when its `error_rate` or its `p95_ms` sits further from that
baseline than the configured number of the baseline's own deviations. The
classification SHALL be made in code rather than by asking the model, and the
same buckets SHALL yield the same classification on every run.

#### Scenario: A minute that leaves the baseline is anomalous
- **GIVEN** a window whose buckets sit at a steady error rate before rising
- **WHEN** the buckets are classified
- **THEN** the earliest bucket that departs from the steady rate is anomalous,
  and the steady ones before it are not

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
  before the window and the next iteration must reach further back

### Requirement: Widening is triggered structurally, not by confidence alone
The system SHALL widen the log window on the next iteration when the earliest
bucket in the current window is already anomalous, because that indicates the
onset precedes the window. Low confidence with iterations remaining SHALL also
trigger widening.

#### Scenario: An anomalous earliest bucket widens the next iteration
- **GIVEN** an iteration whose earliest bucket in the window is anomalous
- **WHEN** the next iteration begins
- **THEN** it requests a strictly wider lookback than the previous iteration

### Requirement: The widening schedule is derived from configuration
The system SHALL derive each iteration's lookback from the configured initial
lookback, maximum window span, and iteration budget, as an increasing sequence
whose first entry is the initial lookback and whose last entry is exactly the
maximum span. No lookback SHALL exceed the maximum span.

#### Scenario: The schedule starts at the initial lookback and ends at the maximum
- **GIVEN** a configured initial lookback, maximum span, and iteration budget
- **WHEN** the widening schedule is derived
- **THEN** it has one entry per iteration, its first entry is the initial
  lookback, and its last entry is the maximum span

#### Scenario: The schedule increases with every step
- **GIVEN** a derived widening schedule
- **WHEN** its entries are compared in order
- **THEN** each is strictly greater than the one before it

#### Scenario: Reconfiguring the budget still ends at the maximum
- **GIVEN** an iteration budget changed to a different number of iterations
- **WHEN** the schedule is derived again
- **THEN** its last entry is still exactly the maximum span

### Requirement: Exhaustion reports insufficient evidence rather than a guess
The system SHALL exit investigation with no determined cause and a confidence
below the mitigate threshold when the iteration budget is spent, or when the
window is already at the maximum span and the earliest bucket remains
anomalous. It SHALL NOT return a hypothesis manufactured to fill the field, and
the outcome SHALL be distinguishable from a confident answer.

#### Scenario: A spent iteration budget escalates
- **GIVEN** an incident where the configured maximum iterations complete with
  no hypothesis reaching the mitigate threshold
- **WHEN** the loop finishes
- **THEN** it reports no determined cause at a confidence below the threshold,
  and the incident routes to `escalated`

#### Scenario: An onset beyond the maximum span escalates
- **GIVEN** a final iteration at the maximum window span whose earliest bucket
  is still anomalous
- **WHEN** the loop finishes
- **THEN** it reports no determined cause, indicating the incident began before
  the retrievable window
