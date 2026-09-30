# alert-supplied-onset Specification

## Purpose
When an incident began, where the service's own series cannot say. The measurement of spec §9 is the authority wherever it finds anything; this is what happens when it finds nothing and the alert dates its own finding - so that a fault leaving no operational trace is still an incident with a beginning to anchor retrieval on.
## Requirements
### Requirement: A measured onset wins wherever one exists

The system SHALL measure the onset from the retrieved metrics first, and SHALL
use that minute whenever one is found, even where the alert states an onset of
its own.

A measured onset is evidence and a stated one is testimony. The measurement is
made from the buckets Argus retrieved itself and can be re-derived by anyone
reading the incident; a figure in an alert is whatever the thing that fired it
chose to say. Where both exist they should agree, and where they do not the one
that can be checked is the one to keep.

#### Scenario: A stated onset does not displace a measured one
- **GIVEN** an alert carrying an onset, for a window whose series depart
- **WHEN** the onset is decided
- **THEN** it is the minute measured from the metrics

### Requirement: An onset stated by the alert is accepted when none can be measured

The system SHALL use the onset an alert states whenever no onset can be measured
from the retrieved window, and SHALL investigate from it exactly as it would from
a measured one.

This is what lets an incident be found by something other than a health series. A
window that is flat because nothing was ever wrong and a window that is flat
because what is wrong is a value are the same window, and only the alert can tell
them apart.

#### Scenario: A flat window with a stated onset is investigated
- **GIVEN** an alert carrying an onset, for a window in which no series departs
- **WHEN** the investigation runs
- **THEN** it proceeds from the stated onset, and a model is asked

#### Scenario: A flat window with no stated onset ends as it always did
- **GIVEN** an alert carrying no onset, for a window in which no series departs
- **WHEN** the investigation runs
- **THEN** it returns without asking a model, unchanged from the behaviour every
  other incident relies on

### Requirement: The opening message says a stated onset is uncorroborated

The system SHALL tell the model, in the opening message, when the onset it is
working from was stated by the alert rather than measured - that no series
departs across it, and that the metrics therefore carry no evidence about this
incident at all.

Said rather than left implicit, for the reason the "window opens already
elevated" sentence is said: a model handed a flat window and a confident minute
would otherwise read the flatness as the service being well, and conclude there
is nothing to find.

#### Scenario: The model is told the metrics corroborate nothing
- **GIVEN** an investigation working from an onset the alert stated
- **WHEN** the opening message is built
- **THEN** it says the onset came from the alert and that no series departs
  across it

#### Scenario: A measured onset is described as it always was
- **GIVEN** an investigation working from a measured onset
- **WHEN** the opening message is built
- **THEN** it says the onset was measured from the per-minute metrics, unchanged

### Requirement: A stated onset may sit outside everything retrievable

The system SHALL accept an onset older than the span the metrics source keeps,
and SHALL address the change channels at that minute rather than at the alert.

An alert that carries its own onset is reporting something found long after it
began. Anchoring the change history on when the alert fired would ask what
changed during the discovery rather than during the fault, which for a check that
runs weekly is a week of changes and no answer.

#### Scenario: The change channels are read at the stated onset
- **GIVEN** an investigation working from an onset a week before the alert fired
- **WHEN** the flag and deploy histories are retrieved
- **THEN** they cover the stated onset, not the minute the alert fired

### Requirement: An alert may state the onset of an absence

The system SHALL accept an onset stated by an alert whose subject is a signal that
stopped, and SHALL treat the minute of the last reading as that onset.

This is the second thing an alert knows that no series can say, and it is the
sharper of the two. A rule watching for a signal's absence fires because readings
that were arriving stopped arriving, and the minute they stopped is the onset
exactly. Nothing in the retrieved window marks it, because what marks it is the
first minute that is missing.

#### Scenario: The last reading's minute is investigated from
- **GIVEN** an alert reporting a signal absent, stating the minute of the last
  reading
- **WHEN** the investigation runs
- **THEN** it proceeds from that minute, and a model is asked

### Requirement: Where the minutes are absent the stated onset is the only source

The system SHALL treat an alert's stated onset as the whole of the dating wherever
the minutes that would carry a departure are the missing ones, rather than as a
fallback used because measurement happened to fail.

A measured onset outranks a stated one wherever both exist, and that rule is
unchanged. It has nothing to reach here: a departure is measured from minutes, and
the minutes after this onset do not exist. Said explicitly so that a later change
preferring measurement more strongly does not leave this case undatable, and so
that nobody reads the stated minute as a second-best.

#### Scenario: Nothing is measured from minutes that are not there
- **GIVEN** a window whose rows stop at the stated onset
- **WHEN** the onset is decided
- **THEN** it is the stated minute, and no measurement is treated as having been
  attempted against the missing span

### Requirement: The distance between the last reading and the alert is measured, not left to the model

The system SHALL work out, where the message is built, how far the alert's firing
is from the last minute the window carries, and SHALL state it.

A model has one of those two figures and Argus has both. The gap is the whole
evidence that the window stops for a reason rather than because retrieval was
short, and nothing else in front of the model says what time it is now - so a
model asked to notice the gap is being asked to subtract a number it was never
given. This is the same reason the window's opening elevation is measured and
passed in rather than described: whether one figure sits before another is a
measurement, not a thing prose can work out.

What is left to the model is what the gap means - a service that went dark, or a
coincidence to be ruled out - which is the judgement this mode is about.

#### Scenario: The message states the gap
- **GIVEN** an investigation whose window stops well before the alert fired
- **WHEN** the opening message is built
- **THEN** it states the last minute the window carries, when the alert fired, and
  that nothing covers the minutes between

#### Scenario: A window that runs to the alert states no gap
- **GIVEN** an investigation whose window carries minutes up to the alert
- **WHEN** the opening message is built
- **THEN** it states no gap

### Requirement: The opening message says the rows stop, and that their stopping is the subject

The system SHALL tell the model, where a window's rows stop before the alert, that
they stop, where they stop, and that their stopping is what the alert reports -
rather than describing the rows that are present as though they were the whole
answer.

A window that stops is the one shape a model reads wrongly without prompting. An
empty table provokes a question; a plausible window that simply ends provokes
none, and the natural reading is that Argus retrieved a short span. Every sentence
about such a window has to be true of the minutes that are missing as well as of
the ones that are there.

#### Scenario: The rows that stop are described as stopping
- **GIVEN** an investigation whose rows stop at the stated onset
- **WHEN** the opening message is built
- **THEN** it says the rows stop there and that their absence is what was alerted
  on, rather than that no series departs across the window

#### Scenario: The model is not told the channel has no more to give
- **GIVEN** the same investigation
- **WHEN** the opening message is built
- **THEN** it does not tell the model that the rows are the whole span the source
  keeps, nor that there is no more of that channel to ask for

#### Scenario: A missing minute is not described as a missing reading
- **GIVEN** the same investigation
- **WHEN** the opening message is built
- **THEN** what it says about absence is about minutes with no row, not about
  cells with no value

### Requirement: A window that was read throughout reads exactly as it did

The system SHALL leave every sentence about a window whose minutes are all present
unchanged, whether its onset was measured or stated.

Two of the three cases predate this capability's second incident and are relied on
by every scenario built before it: a measured onset over a window that departs, and
a stated onset over a window that is flat. A window that stops is a third case and
takes a third wording, rather than a caveat bolted to either of the first two.

#### Scenario: A flat window with a stated onset is described as before
- **GIVEN** an investigation whose window carries every minute and departs nowhere
- **WHEN** the opening message is built
- **THEN** it says no series departs across the window, unchanged

#### Scenario: A measured onset is described as before
- **GIVEN** an investigation whose onset was measured from the window
- **WHEN** the opening message is built
- **THEN** it says the onset was measured from the per-minute metrics, unchanged

