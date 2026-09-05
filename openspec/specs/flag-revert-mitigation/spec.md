# flag-revert-mitigation Specification

## Purpose
What the Mitigation agent does once a cause has been named: choose a reversible
action deterministically, identify the flag to put back from what the provider
recorded as changing, take the action, and measure the verdict from re-queried
metrics - undoing the action when that verdict refutes it.
## Requirements
### Requirement: A reversible action is chosen from the cause, in code
The Mitigation agent SHALL derive the action to take from the hypothesis's
`cause_type` and the subject it names, deterministically and without asking a
model. A cause with no mapped reversible action SHALL yield no action rather
than an approximate one.

Reading the Investigator's conclusion is not a second investigation: choosing an
action stays a pure function of the hypothesis and the recorded changes handed
to it, with no retrieval of its own and no judgement about what caused the
incident.

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
The Mitigation agent SHALL revert the flag the hypothesis names, confirmed
against the flag changes the provider recorded in the environment over a recent
window. The hypothesis says *which* flag; the provider's history says whether it
really changed and in which direction, and that history remains the only
authority for the direction of the revert.

Where the hypothesis names a flag the provider recorded as changing, that is the
flag. Where it names one the provider recorded no change for, the agent SHALL
take no action and the incident SHALL escalate - the Investigator named
something the environment does not corroborate, which is a disagreement a human
resolves rather than a write Argus should guess at.

Where the hypothesis names no flag, the agent SHALL fall back to the history
alone: exactly one changed flag is the flag; none, or several, takes no action
and escalates.

Where a flag changed more than once, the latest of its changes is the one
undone. Current state alone SHALL NOT be used to identify the flag: a flag
switched off into an incident is indistinguishable by evaluation from one that
has been off all along. The flag name SHALL NOT come from Argus's own
configuration, which would hardcode one environment's answer into the agent.

#### Scenario: The flag the hypothesis names is the one reverted
- **GIVEN** a flag-toggle hypothesis naming a flag, and a history in which that
  flag and one other both changed
- **WHEN** mitigation runs
- **THEN** the named flag is the one changed back, and the other is left alone

#### Scenario: A named flag the provider never recorded escalates
- **GIVEN** a flag-toggle hypothesis naming a flag the provider recorded no
  change for
- **WHEN** mitigation runs
- **THEN** no flag is changed and the incident escalates

#### Scenario: The direction comes from the history, not from the hypothesis
- **GIVEN** a flag-toggle hypothesis naming a flag the provider recorded as
  having been switched off
- **WHEN** mitigation runs
- **THEN** the flag is switched on, whatever direction the hypothesis's prose
  described

#### Scenario: The changed flag is the one reverted
- **GIVEN** exactly one flag changed in the window and a flag-toggle hypothesis
  naming no flag
- **WHEN** mitigation runs
- **THEN** that flag is the one changed back

#### Scenario: A flag toggled more than once is put back to its state before the latest change
- **GIVEN** a flag was toggled twice in the window and a flag-toggle hypothesis
- **WHEN** mitigation runs
- **THEN** the flag is set to the state it held before the later of the two
  changes

#### Scenario: An ambiguous environment escalates rather than guessing
- **GIVEN** more than one flag changed in the window and a flag-toggle
  hypothesis naming no flag
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

### Requirement: One action per candidate, enforced by the database
The system SHALL record an action before taking it, and SHALL permit at most
one action per incident and candidate. The record SHALL be what claims the
right to act: a walk that cannot write it SHALL NOT take the action, and SHALL
NOT announce one. The system SHALL NOT decide this by reading first and acting
after, because two walks reading at the same moment would both find nothing and
both act.

#### Scenario: A resumed walk does not act a second time
- **GIVEN** an incident whose action for a candidate is already recorded
- **WHEN** the mitigation node runs again for that same candidate
- **THEN** no action is taken, no second attempt is announced, and the answer
  is the outcome already recorded

#### Scenario: The walk that claims the action is the one that takes it
- **GIVEN** an incident with no action yet recorded for a candidate
- **WHEN** the mitigation node runs for it
- **THEN** the action is taken and its outcome recorded against the claim

### Requirement: An action claimed but never answered for is settled by the provider
The system SHALL treat a recorded action carrying no outcome as unresolved
rather than as taken or as untaken, and SHALL ask the flag provider's own
record whether the change reached it. Where the provider records the change,
the incident SHALL escalate: the change was made and nothing measured what
followed, and no verdict can be invented for it. Where the provider records no
such change, the system SHALL take the action. Where the provider cannot say -
unreachable, or attributing nothing to Argus because it shares a credential
with its operators - the incident SHALL escalate rather than act on the guess.

#### Scenario: A change that landed but was never measured escalates
- **GIVEN** an action recorded with no outcome, whose change the provider
  records as made
- **WHEN** the walk resumes
- **THEN** the incident escalates, and no second action is taken

#### Scenario: A change that never landed is taken now
- **GIVEN** an action recorded with no outcome, and a provider recording no
  such change
- **WHEN** the walk resumes
- **THEN** the action is taken and its outcome recorded

#### Scenario: A provider that cannot say is not read as nothing having happened
- **GIVEN** an action recorded with no outcome, and a provider that cannot
  answer whether the change was made
- **WHEN** the walk resumes
- **THEN** the incident escalates rather than acting again

### Requirement: Argus can recognise its own change in the provider's record
The system SHALL be able to determine whether a recorded flag change was made
by Argus itself, from the author the provider attributes it to. A deployment
that cannot make that distinction SHALL report that it cannot, and SHALL NOT
report that no such change was made.

#### Scenario: Argus's own change is recognised as its own
- **GIVEN** a flag Argus changed through its own credential
- **WHEN** the provider's record is asked about that flag
- **THEN** the change is recognised as Argus's

#### Scenario: Somebody else's change to the same flag is not Argus's
- **GIVEN** a flag changed by a person rather than by Argus
- **WHEN** the provider's record is asked about that flag
- **THEN** the change is not reported as Argus's

#### Scenario: A deployment that cannot attribute says so
- **GIVEN** a deployment whose credential the provider attributes to nobody in
  particular
- **WHEN** the provider's record is asked whether Argus made a change
- **THEN** the answer is that it cannot be known, distinguishably from no
  change having been made

