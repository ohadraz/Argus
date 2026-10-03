## MODIFIED Requirements

### Requirement: An alert-dated incident is unconfirmable only where its channel has nothing left to show

The system SHALL treat an action as unconfirmable where the incident's onset was
stated by the alert, the readings already cover the minutes the incident is about,
**and** the action proposed reports nothing about what it changed. It SHALL NOT
treat an action as unconfirmable where those minutes carry no reading at all, nor
where the action's own answer states what it changed.

An onset stated rather than measured was the whole of this judgement once, and the
inference behind it was sound: the alert dated the incident because no series
departed, a series that never departed cannot be watched coming back, so nothing
would say whether an action worked. The last step is what fails, and it fails
twice. A channel can be watched coming back in two ways - a level falling, or a
reading existing - and an incident whose minutes were never published is waiting on
the second. And the service's window is not the only witness: an action whose answer
is a statement about the world rather than an acknowledgement of a request has
already said what it did.

So the alert-dated shapes part company on their evidence rather than on their mode:

- Readings cover the incident's minutes, flat throughout, and the action would
  report nothing. The channel is already saying everything it will ever say, and it
  will say the same thing after the change goes back. Unconfirmable, as it has
  always been.
- No reading covers them. The channel is saying nothing yet and will say something,
  and the saying-something is the confirmation.
- The action reports what it changed. The witness is the action rather than the
  channel, and a flat window is not asked.

Read back-to-front on first sight, and correct: an alert-dated incident that still
has readings has already shown its answer, one with none has a return to look
forward to, and one whose action answers for itself needs neither.

#### Scenario: An incident whose minutes are all present is still unconfirmable
- **GIVEN** an incident whose onset the alert stated, whose window carries a
  reading for every minute since that onset, and whose proposed action reports
  nothing about what it changed
- **WHEN** the proposed action reaches the gate
- **THEN** it is refused as unconfirmable and recommended rather than taken

#### Scenario: An incident whose minutes are absent is acted on
- **GIVEN** an incident whose onset the alert stated and whose window carries no
  reading at or after that onset
- **WHEN** the proposed action reaches the gate
- **THEN** it is not refused as unconfirmable, and the action is taken

#### Scenario: An action that reports its own effect is acted on
- **GIVEN** an incident whose onset the alert stated and whose window is flat
  throughout, and whose proposed action answers with what it changed
- **WHEN** the proposed action reaches the gate
- **THEN** it is not refused as unconfirmable, and the action is taken

#### Scenario: A measured onset is unaffected
- **GIVEN** an incident whose onset was measured from its own series
- **WHEN** the proposed action reaches the gate
- **THEN** confirmability is not what decides it, exactly as before

## ADDED Requirements

### Requirement: Whether an action answers for itself is a property of its kind

The system SHALL decide whether an action reports what it changed from the action's
kind, declared once in code beside the kind itself, and SHALL NOT infer it from a
particular call's answer.

The gate judges before the action is taken, so there is no answer yet to inspect.
Declaring it with the kind also keeps the judgement reviewable: which actions can
answer for themselves is a short list somebody maintains, in the same place as which
actions may be taken unasked.

#### Scenario: The kind says whether a receipt is coming
- **GIVEN** a proposed action of a kind declared as reporting what it changes
- **WHEN** the gate asks whether confirmation can arrive
- **THEN** it answers yes, before anything has been performed

#### Scenario: A kind that reports nothing is treated as before
- **GIVEN** a proposed action of a kind that is not declared as reporting what it
  changes
- **WHEN** the gate asks whether confirmation can arrive
- **THEN** the window decides, as it did before this distinction existed
