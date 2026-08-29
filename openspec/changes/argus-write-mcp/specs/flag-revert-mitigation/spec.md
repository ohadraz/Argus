## ADDED Requirements

### Requirement: A reversible action is chosen from the cause, in code
The Mitigation agent SHALL derive the action to take from the hypothesis's
`cause_type`, deterministically and without asking a model. A cause with no
mapped reversible action SHALL yield no action rather than an approximate one.

#### Scenario: A flag-toggle cause yields a flag revert
- **GIVEN** a hypothesis whose cause is a feature-flag toggle
- **WHEN** an action is proposed for it
- **THEN** the proposed action is to put the flag back to the state it held
  before the change

#### Scenario: A cause with no reversible action yields none
- **GIVEN** a hypothesis whose cause has no reversible action mapped to it
- **WHEN** an action is proposed for it
- **THEN** no action is proposed, and the incident escalates rather than
  resolving

#### Scenario: Choosing an action reaches no model
- **WHEN** an action is proposed for any hypothesis
- **THEN** no model call is made

### Requirement: The flag to revert is identified from the provider's change history
The Mitigation agent SHALL identify the flag to revert from the flag changes the
provider recorded in the environment over a recent window, rather than from a
flag name configured into Argus or from which flags are currently enabled. Where
exactly one flag changed, that is the flag; where a flag changed more than once,
the latest of its changes is the one undone. Where no flag changed, or more than
one did, the agent SHALL take no action and the incident SHALL escalate.

Current state alone SHALL NOT be used to identify the flag: a flag switched off
into an incident is indistinguishable by evaluation from one that has been off
all along.

#### Scenario: The changed flag is the one reverted
- **GIVEN** exactly one flag changed in the window and a flag-toggle hypothesis
- **WHEN** mitigation runs
- **THEN** that flag is the one changed back

#### Scenario: A flag toggled more than once is put back to its state before the latest change
- **GIVEN** a flag was toggled twice in the window and a flag-toggle hypothesis
- **WHEN** mitigation runs
- **THEN** the flag is set to the state it held before the later of the two
  changes

#### Scenario: An ambiguous environment escalates rather than guessing
- **GIVEN** more than one flag changed in the window and a flag-toggle
  hypothesis
- **WHEN** mitigation runs
- **THEN** no flag is changed and the incident escalates

#### Scenario: Nothing changed escalates rather than acting
- **GIVEN** no flag changed in the window and a flag-toggle hypothesis
- **WHEN** mitigation runs
- **THEN** no flag is changed and the incident escalates

### Requirement: A flag is reverted in whichever direction it was changed
The Mitigation agent SHALL undo a flag change in either direction: a flag that
was switched on SHALL be switched off, and a flag that was switched off SHALL be
switched on. An incident caused by a flag being withdrawn is as real as one
caused by a flag being introduced, and an agent that can only turn flags off
cannot mitigate the first at all.

#### Scenario: A flag that was switched on is switched off
- **GIVEN** the flag's latest recorded change enabled it
- **WHEN** the action is taken
- **THEN** the flag is off afterwards, as the provider reports it

#### Scenario: A flag that was switched off is switched on
- **GIVEN** the flag's latest recorded change disabled it
- **WHEN** the action is taken
- **THEN** the flag is on afterwards, as the provider reports it

#### Scenario: The undo descriptor records the state the flag was actually in
- **GIVEN** an action undoing a change that had switched a flag off
- **WHEN** the action's undo descriptor is read
- **THEN** it records the flag as having been off, not as having been on

### Requirement: The verdict is measured from re-queried metrics
After taking an action, the Mitigation agent SHALL re-query the same metrics
channel the Investigator read and SHALL return `confirmed` only where the
service's minutes after the action no longer depart from its baseline. The
judgement of whether a minute departs SHALL be the same one used to locate an
onset, so that the two agents cannot disagree about whether the same minute was
healthy.

#### Scenario: A recovered service confirms the hypothesis
- **GIVEN** an action has been taken and the minutes after it sit at the
  service's baseline
- **WHEN** the verdict is formed
- **THEN** it is `confirmed`

#### Scenario: A service still failing refutes it
- **GIVEN** an action has been taken and the minutes after it still depart from
  the baseline
- **WHEN** the verdict is formed
- **THEN** it is `refuted`

#### Scenario: The verdict is not read from the minute in progress
- **GIVEN** an action taken partway through a minute
- **WHEN** the verdict is formed
- **THEN** it rests on a minute that began after the action, not on the minute
  the action fell inside

#### Scenario: No recovery within the allowed time is refuted, not an error
- **GIVEN** an action has been taken and the service has not returned to
  baseline within the configured time
- **WHEN** the verdict is formed
- **THEN** it is `refuted`

### Requirement: A refuted action is undone
Where an action's verdict is `refuted`, the system SHALL restore the state
recorded in that action's undo descriptor before the incident proceeds. An action
that did not resolve the symptom was taken on a hypothesis the evidence has not
borne out, and leaving its change in place would mean production state was
altered for a cause that was not the cause, with no one told.

#### Scenario: A refuted flag revert puts the flag back
- **GIVEN** a flag was changed and the service's minutes after it still depart
  from the baseline
- **WHEN** the verdict is formed
- **THEN** the flag holds the state named in the undo descriptor again, as the
  provider reports it

#### Scenario: A confirmed action is left in place
- **GIVEN** a flag was changed and the service recovered
- **WHEN** the verdict is formed
- **THEN** the flag keeps the state the action put it in

#### Scenario: A failed restore escalates rather than passing quietly
- **GIVEN** a refuted action whose recorded state cannot be restored
- **WHEN** the restore is attempted
- **THEN** the incident escalates, carrying both the action taken and the failure
  to restore it
