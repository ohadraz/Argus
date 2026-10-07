# deployment-platform-port Specification

## Purpose
How Argus reaches the deployment platform: through a port named for the role and
split by autonomy tier, with one adapter per vendor that alone knows the wire
shape - and how the platform's failures are told apart, so that a platform that
is down narrows the walk and one that said no does not.
## Requirements
### Requirement: The deployment platform is reached through a port named for its role
The system SHALL reach the deployment platform only through a port whose
operations are named for what Argus wants from a platform and return Argus's
own values, never the vendor's wire shape. Exactly one adapter per vendor SHALL
implement it, and no code outside that adapter SHALL know the vendor's routes,
selectors, request bodies or response fields.

The port SHALL be split by autonomy tier: the read server SHALL be handed a port
that can only read, and only the write server SHALL be handed one that can change
the platform.

#### Scenario: A write action asks for intent, not a route
- **WHEN** an action needs the replica count a deployment is running
- **THEN** it asks the port for it and receives a number, and it never builds a
  URL, a selector or a request body

#### Scenario: The read server cannot type a write
- **WHEN** the read server is built
- **THEN** what it is handed offers only the platform's reads

### Requirement: An unreachable platform is told apart from a refusal
The adapter SHALL report a request that never got an answer - a transport failure,
or a status of the server's own fault (5xx) - as the platform being unreachable,
and any other failure as a refusal: a rejected request (4xx), or an answer that
does not say what was asked. Each action SHALL map the two onto its own refusal,
and only the first SHALL carry the mark that tells a caller every action through
this platform is unavailable.

#### Scenario: A platform that is down
- **GIVEN** the platform refuses the connection or answers 503
- **WHEN** an action asks it anything
- **THEN** the action's refusal carries the unreachable-platform mark

#### Scenario: A platform that rejects the request
- **GIVEN** the platform answers 400
- **WHEN** an action asks it to change something
- **THEN** the action's refusal carries no unreachable-platform mark

