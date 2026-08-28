# investigator-react-loop Specification

## Purpose
Covers the `investigating` phase as spec §9's bounded ReAct loop: deterministic
onset detection from the metrics summary, onset-anchored log retrieval that
widens on a derived schedule, the LLM verdict each iteration, and the exit
conditions - including the honest "insufficient evidence" outcome.

## Requirements
### Requirement: The investigating phase runs a bounded iterative loop
The system SHALL run investigation as an iterative loop rather than a single
pass. Each iteration SHALL read log lines for a window anchored on the onset
located in the metrics summary, and produce a hypothesis with a confidence. The
loop SHALL exit as soon as a hypothesis is both confident enough to act on and
trustworthy by the acceptance rule below, and SHALL run no more than the
configured maximum number of iterations.

#### Scenario: A confident first iteration exits immediately
- **GIVEN** an incident whose window shows a calm stretch before the onset, and
  whose first iteration produces a hypothesis at or above the mitigate threshold
- **WHEN** the Investigator investigates
- **THEN** it returns that hypothesis and performs no further iterations

#### Scenario: The iteration budget is never exceeded
- **GIVEN** an incident where no iteration ever reaches the mitigate threshold
- **WHEN** the Investigator investigates
- **THEN** it performs exactly the configured maximum number of iterations and
  no more

### Requirement: The metrics summary is read once, before the loop
The system SHALL read the metrics summary a single time for one fixed, wide
window, rather than once per iteration. Only the log window widens across
iterations. A window in which no minute departs from the baseline SHALL end the
investigation with no determined cause and without asking the model at all.

#### Scenario: No anomalous bucket means no onset and no model call
- **GIVEN** a metrics summary in which no bucket is anomalous
- **WHEN** the Investigator investigates
- **THEN** it does not report a determined cause, does not fabricate an onset,
  and does not ask the model

### Requirement: Log retrieval each iteration starts before the onset and ends at the alert
The system SHALL derive the onset from the metrics summary - the earliest
anomalous bucket within the window - and SHALL request log lines for a window
starting before that onset, so that a change event preceding the first
anomalous minute is retrievable. That window SHALL end at the alert time rather
than a fixed interval past the onset: the onset is inferred and may be wrong,
where the alert is the one moment the service is known to have been unhealthy,
and a window closing before it can exclude the incident entirely. The requested
span SHALL stay within the configured maximum, giving way at the start rather
than at the end.

#### Scenario: The window starts before the onset
- **GIVEN** a metrics summary whose earliest anomalous bucket is at some minute
- **WHEN** the Investigator retrieves log lines for that iteration
- **THEN** the requested window starts strictly before that minute

#### Scenario: The window reaches the alert
- **GIVEN** an alert that fired well after the onset located in the metrics
- **WHEN** the Investigator retrieves log lines for that iteration
- **THEN** the requested window ends at the alert time, covering the minutes
  between the onset and it

### Requirement: A minute is anomalous relative to the window's own baseline
The system SHALL classify a metric bucket by comparing it against the calm
stretch of the same window, not against an absolute configured value. A bucket
SHALL be anomalous when its `error_rate` or its `p95_ms` sits further from that
baseline than the configured number of the baseline's own deviations. The
baseline's spread SHALL be measured against the calm stretch's own worst
minutes rather than its average deviation, which reads as zero whenever a
metric takes few distinct values - a sampled error rate is quantised into steps,
so most quiet minutes report the identical figure however much the rate moves,
and a spread derived from their average collapses the threshold onto the
baseline. The classification SHALL be made in code rather than by asking the
model, and the same buckets SHALL yield the same classification on every run.

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

### Requirement: A confident answer from a window with no visible start is not trusted on sight
The system SHALL withhold acceptance of an otherwise-confident hypothesis when
the earliest bucket in the metrics window is anomalous, because the onset
located there is only a lower bound and the first log window therefore did not
contain the incident's start. In that case the loop SHALL widen and ask again
before accepting an answer. This check SHALL be made from the metrics summary
in code, never from the model's own account of its certainty, since a model
that formed a hypothesis from too little evidence reports high confidence and
cannot miss what it was never shown.

#### Scenario: A confident first answer from a mid-incident window costs one widening
- **GIVEN** a metrics window whose earliest bucket is anomalous
- **WHEN** the first iteration produces a hypothesis at or above the mitigate
  threshold
- **THEN** the Investigator does not return it immediately, and asks the model
  again on a strictly wider log window

#### Scenario: The better-informed answer is the one returned
- **GIVEN** a metrics window whose earliest bucket is anomalous, and two
  confident hypotheses in turn
- **WHEN** the loop accepts an answer
- **THEN** it returns the hypothesis from the wider window, not the first one

#### Scenario: A confident answer is kept when later iterations are unsure
- **GIVEN** a first iteration that was confident but not trusted, followed by
  iterations that never reach the threshold again
- **WHEN** the iteration budget is spent
- **THEN** the Investigator returns that confident hypothesis rather than
  reporting no cause

### Requirement: Widening reaches strictly further back each iteration
The system SHALL request a strictly earlier log window start on each successive
iteration, so that an iteration can see something the previous one could not.

#### Scenario: Each iteration reaches further back than the last
- **GIVEN** an investigation that runs more than one iteration
- **WHEN** its log retrieval calls are compared in order
- **THEN** each requested window starts strictly earlier than the one before it

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
The system SHALL exit investigation with no determined cause and no confidence
when the iteration budget is spent without any hypothesis having been accepted,
or when no minute in the metrics window was anomalous. It SHALL NOT return a
hypothesis manufactured to fill the field, and the outcome SHALL be
distinguishable from a confident answer. The reported reason SHALL distinguish
an incident that began before the retrievable window from one where the
evidence was read and still explained nothing.

#### Scenario: A spent iteration budget escalates
- **GIVEN** an incident where the configured maximum iterations complete with
  no hypothesis reaching the mitigate threshold
- **WHEN** the loop finishes
- **THEN** it reports no determined cause and no confidence, and the incident
  routes to `escalated`

#### Scenario: An onset beyond the maximum span escalates
- **GIVEN** a final iteration at the maximum window span whose earliest bucket
  is still anomalous
- **WHEN** the loop finishes
- **THEN** it reports no determined cause, indicating the incident began before
  the retrievable window

### Requirement: The loop retrieves change events as a third input
The system SHALL retrieve the changes made to the service before investigating,
once per investigation over the configured change lookback, and SHALL include
them in the evidence shown to the model alongside the metric buckets and the
log lines. The retrieval SHALL happen once rather than per iteration, for the
same reason the metrics summary does: the window is already wide and the rows
are sparse, so re-reading returns what was already read.

The change window SHALL end at the onset and reach back from it by the
configured lookback. A change made after the incident began did not begin it,
and offering it as a candidate invites attribution by mere proximity.

#### Scenario: The change window ends at the onset
- **GIVEN** a metrics summary whose earliest anomalous bucket is at some minute
- **WHEN** the Investigator retrieves change events
- **THEN** the requested window ends at that minute and starts the configured
  change lookback before it

#### Scenario: Change events reach the model as evidence
- **GIVEN** a change source reporting a change before the incident's onset
- **WHEN** the Investigator asks the model for a hypothesis
- **THEN** the evidence it shows includes that change event

#### Scenario: Changes are retrieved once across a widening investigation
- **GIVEN** an investigation that runs more than one iteration
- **WHEN** its retrieval calls are counted
- **THEN** change events were retrieved once, while log lines were retrieved
  once per iteration

#### Scenario: A cause older than the log window is still visible
- **GIVEN** a change that occurred further before the onset than any log window
  the loop is permitted to request
- **WHEN** the Investigator investigates
- **THEN** that change is still among the evidence shown to the model

### Requirement: A failed change retrieval stops the investigation rather than shrinking it
The system SHALL let a change-source failure surface as a failure, and SHALL
NOT continue with logs alone while reporting a cause as though the change
evidence had been seen and found empty.

#### Scenario: An unreachable change source does not become a quiet logs-only investigation
- **GIVEN** a change source that cannot be reached
- **WHEN** the Investigator investigates
- **THEN** the investigation fails rather than producing a hypothesis drawn
  from logs alone
