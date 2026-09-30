## ADDED Requirements

### Requirement: An alert-dated incident is unconfirmable only where its channel has nothing left to show

The system SHALL treat an action as unconfirmable where the incident's onset was
stated by the alert **and** the readings already cover the minutes the incident is
about, and SHALL NOT treat it as unconfirmable where those minutes carry no reading
at all.

An onset stated rather than measured has been the whole of this judgement, and the
inference behind it was sound: the alert dated the incident because no series
departed, a series that never departed cannot be watched coming back, so nothing
would say whether an action worked. The last step is what fails. A channel can be
watched coming back in two ways - a level falling, or a reading existing - and an
incident whose minutes were never published is waiting on the second.

So the two alert-dated shapes part company here, and they part on their evidence
rather than on their mode:

- Readings cover the incident's minutes, flat throughout. The channel is already
  saying everything it will ever say, and it will say the same thing after the
  change goes back. Unconfirmable, as it has always been.
- No reading covers them. The channel is saying nothing yet and will say
  something, and the saying-something is the confirmation.

Read back-to-front on first sight, and correct: an alert-dated incident that still
has readings has already shown its answer, and one with none has a return to look
forward to.

#### Scenario: An incident whose minutes are all present is still unconfirmable
- **GIVEN** an incident whose onset the alert stated and whose window carries a
  reading for every minute since that onset
- **WHEN** the proposed action reaches the gate
- **THEN** it is refused as unconfirmable and recommended rather than taken

#### Scenario: An incident whose minutes are absent is acted on
- **GIVEN** an incident whose onset the alert stated and whose window carries no
  reading at or after that onset
- **WHEN** the proposed action reaches the gate
- **THEN** it is not refused as unconfirmable, and the action is taken

#### Scenario: A measured onset is unaffected
- **GIVEN** an incident whose onset was measured from its own series
- **WHEN** the proposed action reaches the gate
- **THEN** confirmability is not what decides it, exactly as before

### Requirement: Whether the readings cover an incident travels with the findings

The system SHALL record, as part of what an investigation hands back, whether any
reading covers the minutes from the incident's onset onwards, and SHALL decide
confirmability from that record rather than re-deriving it.

The gate holds the onset and never the window, and the Investigator holds both. So
the fact is measured once, where the evidence is, and carried on the findings that
already cross that boundary - which keeps the gate's judgement a reading of the
evidence rather than a second measurement of it.

It is a property of the window rather than of the mode, and nothing about it names
one. Any incident dated by its alert whose minutes were never published is judged
this way, whatever the cause turns out to have been.

#### Scenario: The findings say whether the incident's minutes were read
- **GIVEN** an investigation whose window carries no reading at or after the onset
- **WHEN** it hands back what it found
- **THEN** what it hands back says so, beside the candidates and what was read

#### Scenario: A window covering the incident says so too
- **GIVEN** an investigation whose window carries readings throughout
- **WHEN** it hands back what it found
- **THEN** what it hands back says the incident's minutes were read
