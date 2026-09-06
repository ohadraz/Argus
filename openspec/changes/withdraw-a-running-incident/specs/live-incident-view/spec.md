## ADDED Requirements

### Requirement: A live incident can be withdrawn from its page

The view SHALL offer, on a non-terminal incident, a way to withdraw it, and
SHALL NOT offer one on a terminal incident. Withdrawing SHALL require a
deliberate confirmation, because it stops an autonomous response and puts back
what that response changed.

A withdrawn incident SHALL read as withdrawn on the page - distinguishable at a
glance from one Argus resolved and one Argus escalated - and SHALL show what
was undone and what was left as found.

#### Scenario: Withdrawing an incident in progress

- **WHEN** somebody withdraws the incident shown on the page
- **THEN** the incident stops being walked, and the page shows it as withdrawn
  without a manual refresh

#### Scenario: A finished incident offers no withdrawal

- **WHEN** the incident shown has reached a terminal status
- **THEN** the page offers no way to withdraw it

#### Scenario: What was left behind is on the page

- **GIVEN** a withdrawn incident in which one flag was put back and one was
  found changed from outside
- **WHEN** the incident is read
- **THEN** the page says which was which

## MODIFIED Requirements

### Requirement: The live view changes nothing

Nothing the live view exposes SHALL stage, mitigate, approve or delete
anything, and it SHALL hold no incident-domain logic - it renders recorded
events and never decides what they mean.

Withdrawal is the single exception, and is one because it is the human's own
act rather than Argus's: it stops the response and puts back what the response
changed, and it is refused - not merely hidden - for an incident that has
already ended. The view SHALL carry none of its logic; it names the incident
and the orchestrator decides everything else.

#### Scenario: A request to the live view

- **WHEN** any route the live view serves is called, other than the withdrawal
- **THEN** no incident, hypothesis, action, timeline or event row is created,
  modified or deleted

#### Scenario: Withdrawal decides nothing on the page

- **WHEN** the withdrawal is invoked from the page
- **THEN** the page passes on which incident it is and no more, and whether the
  withdrawal is permitted is decided where the incident lives
