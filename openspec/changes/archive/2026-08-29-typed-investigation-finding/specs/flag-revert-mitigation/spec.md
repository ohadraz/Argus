## MODIFIED Requirements

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
