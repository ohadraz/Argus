## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Widening reaches strictly further back each iteration
**Reason**: There are no iterations to compare. The model chooses each window, and may
legitimately re-read a narrower one - to re-check a minute it now has a reason to look at
- which this requirement forbids. The budget bounds the waste that permits.
**Migration**: The property this protected - that an investigation can see something a
previous look could not - is now carried by `investigation-budget`, which bounds total
retrieval rather than mandating its direction, and by the eval suite, which measures
whether the model actually widens when it should.

### Requirement: The widening schedule is derived from configuration
**Reason**: There is no schedule. `log_initial_lookback_minutes` and
`log_max_window_minutes` survive as the default and the clamp on a window the model asks
for; the ladder between them, and `investigation_max_iterations` as its rung count, are
gone.
**Migration**: Replace `investigation_max_iterations` with the tool-call, token and
wall-clock bounds in `investigation-budget`. `agent_investigator.widening` is deleted.

### Requirement: Log retrieval each iteration starts before the onset and ends at the alert
**Reason**: The window is the model's to choose, so a requirement that every window take
a particular shape no longer describes the system. The reasoning behind it - a cause lands
in a minute that still looks healthy, and the alert is the one moment the service is known
to have been unhealthy - moves into the opening message, where it informs the model's
choice rather than removing it.
**Migration**: The default window offered when the model names none keeps exactly this
shape, and the maximum-span clamp still gives way at the start rather than the end, as
`two-phase-retrieval` requires of the read tier.
