# investigator-react-loop Specification

## Purpose
Covers the `investigating` phase as spec §9's bounded loop: deterministic onset
detection from the metrics summary, the retrieval the model asks for over the
windows it names, and the exit conditions - including the honest "insufficient
evidence" outcome.

## Requirements
### Requirement: The investigating phase runs a bounded iterative loop
The system SHALL run investigation as a bounded multi-turn exchange with the model
rather than a single pass. Each turn SHALL let the model call a retrieval tool or answer,
and the exchange SHALL end when the model produces a typed answer or when a configured
bound is reached, whichever comes first. How many turns an investigation takes SHALL NOT
be fixed in advance: an incident whose cause is evident from one channel SHALL be
answerable without reading the others.

#### Scenario: A confident answer from one channel ends the investigation
- **GIVEN** an incident whose change events plainly account for the departure
- **WHEN** the model reads them and answers
- **THEN** the investigation returns that answer and performs no further retrieval

#### Scenario: The bound is never exceeded
- **GIVEN** an incident on which the model never produces an answer
- **WHEN** the investigation runs
- **THEN** it ends at the first configured bound reached and makes no further tool calls

### Requirement: The metrics summary is read once, before the loop
The system SHALL read the metrics summary a single time before the conversation with the
model is opened, for one fixed, wide window, and SHALL locate the onset from it. A window
in which no minute departs from the baseline SHALL end the investigation with no
determined cause and without opening the conversation at all. The model MAY read metrics
again over another window as an ordinary tool call.

#### Scenario: No anomalous bucket means no onset and no model call
- **GIVEN** a metrics summary in which no bucket is anomalous
- **WHEN** the Investigator investigates
- **THEN** it does not report a determined cause, does not fabricate an onset,
  and does not ask the model

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
The system SHALL state to the model, as a fact in the opening message, that the onset it
is given is only a lower bound whenever the earliest bucket in the metrics window is
anomalous - because the incident began before anything retrievable and a confident answer
from that evidence is least trustworthy and least detectable. This determination SHALL be
made from the metrics summary in code, never from the model's own account of its
certainty. The system SHALL NOT withhold the model's answer on this ground, since the
model can now widen its own window and is told why it might need to.

#### Scenario: A lower-bound onset is stated as such
- **GIVEN** a metrics window whose earliest bucket is anomalous
- **WHEN** the conversation is opened
- **THEN** the opening message says the onset is a lower bound and that the incident
  began before the retrievable window

#### Scenario: A visible start is not qualified
- **GIVEN** a metrics window with a calm stretch before its onset
- **WHEN** the conversation is opened
- **THEN** the opening message states the onset without that qualification

### Requirement: Exhaustion reports insufficient evidence rather than a guess
The system SHALL exit investigation with no determined cause and no confidence when a
configured bound is reached without the model having answered, or when no minute in the
metrics window was anomalous. It SHALL NOT return a hypothesis manufactured to fill the
field, and the outcome SHALL be distinguishable from a confident answer. The reported
reason SHALL distinguish an incident that began before the retrievable window, one where
the evidence was read and still explained nothing, and one that ran out of budget.

#### Scenario: A spent budget escalates
- **GIVEN** an incident where a configured bound is reached with no answer from the model
- **WHEN** the loop finishes
- **THEN** it reports no determined cause and no confidence, says which bound ended it,
  and the incident routes to `escalated`

#### Scenario: An onset beyond the retrievable window escalates
- **GIVEN** a metrics window whose earliest bucket is anomalous and a model that reads
  the widest window available and still identifies nothing
- **WHEN** the loop finishes
- **THEN** it reports no determined cause, indicating the incident began before the
  retrievable window

### Requirement: The loop retrieves change events as a third input
The system SHALL offer change-event retrieval to the model as one of its tools, over a
window the model names, so that a change preceding the onset is reachable. The system
SHALL NOT retrieve change events on the model's behalf before it is asked, and SHALL NOT
require that they be read: an incident answerable from logs alone SHALL be answerable
without paying for them.

The default change window offered to the model SHALL end at the onset and reach back from
it by the configured lookback. A change made after the incident began did not begin it,
and offering it as a candidate invites attribution by mere proximity.

#### Scenario: The default change window ends at the onset
- **GIVEN** a model that calls the change-events tool without naming a window
- **WHEN** the call is dispatched
- **THEN** the window requested ends at the onset and starts the configured change
  lookback before it

#### Scenario: Change events reach the model as a tool result
- **GIVEN** a change source reporting a change before the incident's onset
- **WHEN** the model calls the change-events tool
- **THEN** that change event is in the result it receives

#### Scenario: A cause older than any log window is still reachable
- **GIVEN** a change that occurred further before the onset than the maximum log span
- **WHEN** the model calls the change-events tool over the change lookback
- **THEN** that change is in the result it receives

### Requirement: A failed change retrieval stops the investigation rather than shrinking it
The system SHALL let a change-source failure surface as a failure, and SHALL
NOT continue with logs alone while reporting a cause as though the change
evidence had been seen and found empty. This SHALL apply when the model calls the tool
and it fails; it SHALL NOT apply when the model chose not to call it at all.

#### Scenario: An unreachable change source does not become a quiet logs-only investigation
- **GIVEN** a change source that cannot be reached
- **WHEN** the model calls the change-events tool
- **THEN** the investigation fails rather than producing a hypothesis drawn
  from logs alone

#### Scenario: Not asking for changes is not a failure
- **GIVEN** an investigation the model answered from logs and metrics alone
- **WHEN** the investigation finishes
- **THEN** it returns that answer, and the unread change channel is not an error
