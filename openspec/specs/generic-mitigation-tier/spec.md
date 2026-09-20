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
