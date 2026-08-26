# argo-deploy-adapter Specification

## Purpose
The deploy change source: reads an Argo CD server's application state and maps its revision history onto vendor-neutral change events, so nothing above the retrieval boundary learns that Argo CD is what answered.
## Requirements

### Requirement: Deploys are read from an Argo CD-shaped API
The system SHALL retrieve deploy history by requesting an application's state
from an Argo CD server, at a configured base URL and application path, and
SHALL read the deploy history from that response's revision history. The
request SHALL be the one a real Argo CD server answers, so that the adapter is
usable against a real server and not only against a stand-in.

#### Scenario: The adapter requests the configured application
- **GIVEN** a configured Argo base URL and application path
- **WHEN** deploys are retrieved for a service
- **THEN** the adapter requests that path on that base URL, naming the service
  as the application

#### Scenario: Revision history becomes deploy events
- **GIVEN** an Argo response whose application has revision history entries
- **WHEN** the adapter maps the response
- **THEN** each entry becomes a deploy change event carrying the time it was
  deployed and the revision that was deployed

### Requirement: The adapter authenticates when a token is configured
The system SHALL send a configured bearer token with every request to the Argo
server, and SHALL omit the authorization entirely when no token is configured -
so a stand-in that requires none is reachable without inventing a credential.

#### Scenario: A configured token is sent
- **GIVEN** a configured Argo authentication token
- **WHEN** the adapter requests deploy history
- **THEN** the request carries that token as a bearer credential

#### Scenario: No token means no authorization header
- **GIVEN** no configured Argo authentication token
- **WHEN** the adapter requests deploy history
- **THEN** the request carries no authorization credential, and no placeholder
  credential is invented

### Requirement: The adapter filters the window itself
The system SHALL filter retrieved deploy history to the requested window within
the adapter, because the Argo API accepts no time parameters and answers with
an application's entire history. The window semantics SHALL be identical to
those of any other change source, so that no caller can tell which source
filtered where.

#### Scenario: History outside the window is discarded
- **GIVEN** an Argo response containing deploys both inside and outside the
  requested window
- **WHEN** the adapter maps the response
- **THEN** only the deploys inside the window are returned

### Requirement: The deploy time is taken from the field Argo always sets
The system SHALL anchor each deploy event on the time the revision was
deployed, which Argo always reports, and SHALL treat the deploy start time as
optional - read when present, never required.

#### Scenario: A deploy without a start time is still an event
- **GIVEN** an Argo revision history entry that reports no deploy start time
- **WHEN** the adapter maps it
- **THEN** a deploy event is produced, anchored on the time it was deployed
