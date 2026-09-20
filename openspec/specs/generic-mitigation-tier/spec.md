# generic-mitigation-tier Specification

## Purpose
What admits an action Argus may take without asking: membership of a
declared, closed set of generic mitigations, decided by the action's kind
rather than by whether the change could be put back. The undo descriptor
keeps its job - unwinding a refuted or withdrawn change - and a repeatable
mitigation is bounded by a cap rather than by an approval step.
## Requirements
### Requirement: Autonomy is decided by membership of a closed set of mitigations
The system SHALL take an action without human approval only when that action's
kind belongs to a declared, closed set of generic mitigations. Membership SHALL
be a property of the kind, declared once in code, and an action of a kind absent
from that set SHALL never be taken autonomously.

This is the criterion both industry frames use. Google SRE's generic mitigations
are a defined, closed set - drain, roll back, restart, add capacity - applied
before the cause is known; ITIL's standard change is pre-authorised because the
procedure is routine and well understood, not because it can be reversed. The
set SHALL be small enough to be read in one sitting, and adding to it SHALL be a
line somebody writes and defends rather than a property an action can acquire by
being implemented.

#### Scenario: An action in the set is taken without approval
- **GIVEN** a proposed action whose kind is a declared generic mitigation
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, and the action is announced and recorded

#### Scenario: An action outside the set is refused
- **GIVEN** a proposed action whose kind is not in the set
- **WHEN** the gate is asked whether it may proceed
- **THEN** it is refused, the refusal is recorded with its reason, and no
  mutating call is made

#### Scenario: An unregistered kind is refused rather than assumed safe
- **GIVEN** a proposed action of a kind nothing has declared
- **WHEN** the gate is asked whether it may proceed
- **THEN** it is refused - absence from the set is a refusal, never a default to
  permitted

### Requirement: An undo descriptor is how a mitigation is unwound, not whether it is allowed
The system SHALL record an undo descriptor for a mitigation that has one, and
SHALL use it to put the change back when the hypothesis behind it is refuted or
when the incident is withdrawn. The presence of an undo descriptor SHALL NOT be
the condition under which an action may be taken.

The two were the same rule while flag reversion was the only mitigation
implemented, and separating them is what lets a restart be taken at all: it
changes no persistent state, so there is nothing to put back, and requiring a
descriptor would either refuse the action or force a dishonest value into the
record.

#### Scenario: A refuted mitigation with an undo is put back
- **GIVEN** a mitigation that recorded an undo descriptor, whose hypothesis was
  then refuted
- **WHEN** the walk moves on
- **THEN** the change is put back using that descriptor

#### Scenario: A refuted mitigation with nothing to undo is left alone
- **GIVEN** a mitigation that changed no persistent state and so recorded no
  undo descriptor, whose hypothesis was then refuted
- **WHEN** the walk moves on
- **THEN** no undo is attempted, and the absence is recorded as having nothing
  to put back rather than as a failure to put it back

### Requirement: A mitigation that can be repeated is bounded by a cap
The system SHALL bound how many times one kind of generic mitigation may be
applied to one subject within one incident, and SHALL refuse further attempts
once the bound is reached. The risk a repeatable mitigation carries is
repetition rather than irreversibility - a restart loop is the recognised
failure mode, and the control real operators use for it is a limit, not an
approval step.

#### Scenario: A repeated mitigation is refused once the cap is reached
- **GIVEN** an incident in which a mitigation has already been applied to a
  subject as many times as the configured cap allows
- **WHEN** the same mitigation is proposed again for that subject
- **THEN** it is refused, the refusal names the cap, and the walk moves on to
  another candidate or escalates

#### Scenario: The cap is per incident and per subject
- **GIVEN** a mitigation applied to one subject up to its cap
- **WHEN** the same mitigation is proposed for a different subject in the same
  incident
- **THEN** it is allowed

### Requirement: A determined mode that nothing in the set answers is refused in its own words
The system SHALL distinguish two silences at the gate. An incident whose
hypothesis names no mode, or whose mode names no action anything could
identify, SHALL be refused as a mitigation nobody could propose. An incident
whose mode *is* determined, and which no member of the closed set of generic
mitigations answers, SHALL be refused as a failure this system has no
mitigation for.

The distinction SHALL be published on the refusal and SHALL reach the candidate's
own row, the timeline and the postmortem in words a reader can act on: the first
says somebody has to work out what to do, the second says somebody outside this
system has to do it.

Which of the two a refusal is SHALL be answered by the policy that holds the set
of mitigations, not by the gate keeping a second copy of it.

#### Scenario: A mode with no mitigation is refused as such
- **GIVEN** a hypothesis naming a mode that no generic mitigation answers
- **WHEN** the gate is reached with no proposed action
- **THEN** the refusal recorded and published is that nothing in the set answers
  this kind of failure, and no mutating call is made

#### Scenario: An unidentifiable action is still refused as unproposed
- **GIVEN** a hypothesis naming a mode a generic mitigation does answer, but
  whose action could not be identified from the evidence
- **WHEN** the gate is reached with no proposed action
- **THEN** the refusal recorded is that no mitigation was proposed for this
  cause

#### Scenario: The incident escalates either way
- **GIVEN** either refusal
- **WHEN** no further candidate remains to try
- **THEN** the incident ends escalated, with a postmortem, and no action taken

### Requirement: An undo that restores more than one thing restores all of it
The system SHALL allow a generic mitigation's undo descriptor to record more
than one piece of prior state, and SHALL restore every piece when the mitigation
is undone. An action that had to change a second thing in order to change the
first has left two changes behind, and an undo that put back only the one the
action was named for would leave the environment in a state Argus could not
account for - which is the condition the descriptor exists to prevent.

#### Scenario: Every recorded piece of prior state is restored
- **GIVEN** a performed mitigation whose undo descriptor records two pieces of
  prior state
- **WHEN** it is undone
- **THEN** both are restored

#### Scenario: A partial restore is reported rather than counted as undone
- **GIVEN** a performed mitigation whose undo restores one piece of state and
  fails on another
- **WHEN** the undo is attempted
- **THEN** it is recorded as not fully undone, naming what remains changed, and
  the incident is escalated rather than closed
