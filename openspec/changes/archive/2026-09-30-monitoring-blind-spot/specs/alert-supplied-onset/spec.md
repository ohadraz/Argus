## ADDED Requirements

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
