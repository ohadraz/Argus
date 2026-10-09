## ADDED Requirements

### Requirement: Engagement is read on the platform's own incident

The system SHALL read engagement on the on-call platform's incident linked to
the Argus incident, never by passing Argus's own incident id to the platform.
It SHALL find that incident through the reference recorded when it was linked,
or else through the keys the incident's senders stamped on it, and SHALL
record it once found. When no platform incident can be found, the answer SHALL
say that the incident was not linked to one, distinguishably from "nobody
engaged" and from "could not say".

#### Scenario: Linked by an earlier resolution

- **GIVEN** an Argus incident whose platform incident was recorded when a
  person resolved it there
- **WHEN** engagement is read
- **THEN** it is read on that platform incident

#### Scenario: Found by its key

- **GIVEN** an Argus incident with a Grafana key, and a platform incident
  carrying that key, never linked
- **WHEN** engagement is read
- **THEN** it is read on that platform incident, and the link is recorded

#### Scenario: No platform incident

- **GIVEN** an Argus incident no platform incident carries a key of
- **WHEN** engagement is read
- **THEN** the answer says no on-call incident was linked, with no minutes or
  responders invented
