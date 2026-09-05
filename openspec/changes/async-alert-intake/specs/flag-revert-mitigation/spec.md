## ADDED Requirements

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
