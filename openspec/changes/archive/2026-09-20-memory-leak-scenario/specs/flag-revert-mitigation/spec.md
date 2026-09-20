## MODIFIED Requirements

### Requirement: A generic mitigation is chosen from the cause, in code
The Mitigation agent SHALL derive the action to take from the hypothesis's
`failure_mode` and the subject it names, deterministically and without asking a
model. A cause with no mapped generic mitigation SHALL yield no action rather
than an approximate one.

The action's admissibility SHALL be decided by whether its kind belongs to the
declared set of generic mitigations, not by whether it can be undone. The two
coincided while reverting a flag was the only mitigation implemented, and they
part company for the first mitigation that changes no persistent state: such an
action has nothing to put back, so a rule written as "must be undoable" would
refuse it, while the rule both industry frames actually use - a closed,
pre-authorised set of routine responses - admits it.

Reading the Investigator's conclusion is not a second investigation: choosing an
action stays a pure function of the hypothesis and the recorded changes handed
to it, with no retrieval of its own and no judgement about what caused the
incident.

#### Scenario: A flag-toggle cause yields a flag revert
- **GIVEN** a hypothesis whose cause is a feature-flag toggle
- **WHEN** an action is proposed for it
- **THEN** the proposed action is to put the flag back to the state it held
  before the change

#### Scenario: A resource-leak failure mode yields a restart
- **GIVEN** a hypothesis whose failure mode is a resource leak, naming a service
- **WHEN** an action is proposed for it
- **THEN** the proposed action is to restart that service

#### Scenario: A cause with no generic mitigation yields none
- **GIVEN** a hypothesis whose cause has no generic mitigation mapped to it
- **WHEN** an action is proposed for it
- **THEN** no action is proposed, and the incident escalates rather than
  resolving

#### Scenario: An action that changes nothing to put back is still admitted
- **GIVEN** a proposed action whose kind is a declared generic mitigation and
  which records no undo descriptor
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, and the absence of an undo descriptor is recorded as
  there being nothing to put back rather than as a missing value

#### Scenario: Choosing an action reaches no model
- **WHEN** an action is proposed for any hypothesis
- **THEN** no model call is made
