## MODIFIED Requirements

### Requirement: An action claimed but never answered for is settled by the provider
The system SHALL treat a recorded action carrying no outcome as unresolved
rather than as taken or as untaken. For an action that goes through the flag
provider, the system SHALL ask the provider's own record whether the change
reached it. Where the provider records the change, the incident SHALL escalate:
the change was made and nothing measured what followed, and no verdict can be
invented for it. Where the provider records no such change, the system SHALL
take the action. Where the provider cannot say - unreachable, or attributing
nothing to Argus because it shares a credential with its operators - the
incident SHALL escalate rather than act on the guess.

For an action through any other platform - a restart, a rollback, a scale-out,
a pin - the system SHALL NOT ask the flag provider, whose record knows nothing
of it and would answer "no such change" for a change that was made. Nothing
else records whether Argus's own change to a deployment landed, so the
incident SHALL escalate as an action nothing can account for.

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

#### Scenario: A deployment action is not settled by the flag provider
- **GIVEN** a rollback, a scale-out or a pin recorded with no outcome
- **WHEN** the walk resumes
- **THEN** the flag provider is not asked, no second action is taken, and the
  incident escalates
