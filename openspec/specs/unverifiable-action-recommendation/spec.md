# unverifiable-action-recommendation Specification

## Purpose
What Argus does with an action it worked out and must not take. Autonomy rests on an action's effect being observed (spec §13), so a mitigation nothing could confirm is named for a person rather than performed - which is an ending of its own, distinct from having run out of moves.
## Requirements
### Requirement: An action whose confirmation cannot arrive is named and not taken

The system SHALL refuse to perform a mitigation when the evidence that would
confirm it cannot arrive within the verification window, and SHALL record the
action it refused as a recommendation.

Every action Argus takes unasked rests on being able to find out whether it
worked. Where the only thing that would answer is a check somebody else runs on a
schedule Argus does not control, the answer arrives days later or not at all - so
the action would be taken, reported, and never judged. An organisation that would
not accept that from a person should not accept it from an agent.

Stated as a rule about verification rather than as a mapping from a failure mode,
because the reason is the same reason a person would give and does not belong to
one scenario.

#### Scenario: An unconfirmable action is refused
- **GIVEN** an incident whose recovery cannot be observed within the verification
  window
- **WHEN** Mitigation names an action for it
- **THEN** the action is not performed

#### Scenario: The refused action is kept as the recommendation
- **GIVEN** an action refused because it cannot be confirmed
- **WHEN** the incident's record is read
- **THEN** it names that action as what somebody should do

#### Scenario: A confirmable action is unaffected
- **GIVEN** an incident whose recovery is observable in its own series
- **WHEN** Mitigation names an action for it
- **THEN** it is performed as it always was

### Requirement: This refusal stops the walk rather than reaching for the next candidate

The system SHALL end the mitigation phase when an action is refused as
unconfirmable, and SHALL NOT try the next candidate.

The other refusals reject a particular action - it is outside the estate, it has
been tried enough, it is not a generic mitigation - so another candidate is worth
reaching for. This one rejects the possibility of confirming any action on this
incident, and a second candidate is no better placed than the first.

#### Scenario: No further candidate is tried
- **GIVEN** an incident with more than one candidate cause
- **WHEN** an action is refused as unconfirmable
- **THEN** no further candidate's action is attempted

#### Scenario: The refusal says what it was
- **GIVEN** an action refused as unconfirmable
- **WHEN** the candidate's row is read
- **THEN** it says that nothing could confirm the action within the time Argus
  waits

### Requirement: `RECOMMENDED` is where such an incident ends

The system SHALL derive the status `RECOMMENDED` for an incident in which an
action was named and none was taken because none could be confirmed, and that
status SHALL be terminal.

It is not escalation. Escalation is Argus running out of moves and handing over;
here there is a move and Argus is declining to make it. A reader of an outcome
most needs to know which of those happened - whether somebody must work out what
to do, or go and do a named thing - and a shared status erases exactly that.

#### Scenario: A named-but-untaken action ends at `RECOMMENDED`
- **GIVEN** an incident whose only action was refused as unconfirmable
- **WHEN** its status is derived
- **THEN** it is `RECOMMENDED`

#### Scenario: `RECOMMENDED` is terminal
- **WHEN** a `RECOMMENDED` incident is asked whether it has anywhere left to go
- **THEN** it has not

#### Scenario: Running out of candidates is still escalation
- **GIVEN** an incident in which every candidate was refused for a reason other
  than confirmability
- **WHEN** its status is derived
- **THEN** it is `ESCALATED`

### Requirement: What is still owed is said wherever the incident is reported

The system SHALL state, wherever a `RECOMMENDED` incident is rendered, both the
action nobody took and why nobody took it.

The status exists to say something is owed. An account that showed the diagnosis
and omitted the action would leave a reader with a cause and no next step, which
is worse than escalation - escalation at least announces that a person is needed.

#### Scenario: The dashboard says what is owed
- **GIVEN** a `RECOMMENDED` incident
- **WHEN** its page is served
- **THEN** it names the action and says nothing could confirm it

#### Scenario: The postmortem says what is owed
- **GIVEN** a `RECOMMENDED` incident
- **WHEN** its postmortem is written
- **THEN** the recommended action is among what is still outstanding

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
