## ADDED Requirements

### Requirement: The on-call platform is optional and behind one seam

The system SHALL reach the on-call platform only through a port named for the
role, with each platform an adapter named for its vendor. Nothing above the
port SHALL know a platform's routes, headers, event names or object shapes.
A deployment with no on-call platform configured SHALL behave as though the
feature did not exist: the webhook answers `404`, and no platform is read.

#### Scenario: No platform configured

- **GIVEN** a deployment with no on-call platform credential
- **WHEN** a delivery is posted to the on-call webhook
- **THEN** it is answered `404`, and no incident changes

#### Scenario: Grafana alone is enough

- **GIVEN** a deployment with no on-call platform
- **WHEN** a Grafana alert arrives and is walked to its end
- **THEN** the incident is handled exactly as before, and no platform is read

### Requirement: Only a signed delivery is read

The system SHALL verify every delivery's signature over its raw body with the
configured secret, in constant time, before reading anything in it. An
unverified delivery SHALL be answered `401` and SHALL change nothing. An empty
secret SHALL refuse every delivery.

#### Scenario: A forged delivery

- **WHEN** a delivery arrives whose signature does not match its body
- **THEN** it is answered `401`, and no incident changes

### Requirement: A person's resolution in the platform resolves the Argus incident

When a **person** resolves a platform incident, the system SHALL find the
Argus incident it belongs to and SHALL resolve it as a human resolution:
credited to that person by the name the platform holds, through that platform's
channel, with their resolution note if they gave one. The incident SHALL be
found through the keys its senders stamped on the platform incident, matched
against the references Argus recorded at intake, and the platform's own
incident id SHALL then be recorded as a reference.

#### Scenario: Resolved in PagerDuty with a note

- **GIVEN** an Argus incident from a Grafana alert, and a PagerDuty incident
  that Grafana opened for the same alert group
- **WHEN** a person resolves the PagerDuty incident with the note "rolled back"
- **THEN** the Argus incident is `resolved`, and the timeline says that person
  resolved it from PagerDuty, with the note "rolled back"

#### Scenario: Resolved in PagerDuty without a note

- **GIVEN** a PagerDuty incident with mid-incident notes but no resolution note
- **WHEN** a person resolves it
- **THEN** the resolution is recorded with no note, and no mid-incident note
  stands in for one

#### Scenario: A platform incident Argus never had

- **WHEN** a person resolves a platform incident whose keys match no Argus
  incident
- **THEN** the delivery is accepted, logged, and no incident changes

#### Scenario: The same delivery twice

- **GIVEN** a resolution that was already applied
- **WHEN** the platform delivers it again
- **THEN** the delivery is accepted, and nothing is recorded a second time

### Requirement: A resolution nobody decided does not resolve the incident

The system SHALL NOT resolve an Argus incident when the platform incident was
resolved by anything other than a person. Each of these SHALL be logged with
its reason:

- monitoring cleared the alert: that is a metrics signal, and Argus reads
  recovery from the metrics itself;
- a timeout or automation: nobody decided anything.

A merge SHALL NOT resolve the incident, even though the platform credits the
merge to the person who made it: the incident moved rather than ended. A person
later resolving the incident it was merged into SHALL count, found through the
alerts that moved onto it. A reopen of a
platform incident whose Argus incident is already `resolved` SHALL be logged
and SHALL change nothing.

#### Scenario: Monitoring cleared the alert

- **WHEN** the platform incident is resolved by its monitoring integration
- **THEN** the Argus incident is unchanged

#### Scenario: A person merges it into another

- **WHEN** a person merges the platform incident into another
- **THEN** the Argus incident is unchanged

#### Scenario: Merged, then resolved by a person

- **GIVEN** a platform incident merged into another
- **WHEN** a person resolves the incident it was merged into
- **THEN** the Argus incident is `resolved`, credited to that person

#### Scenario: Reopened after Argus resolved it

- **GIVEN** an Argus incident `resolved` from the platform
- **WHEN** the platform incident is reopened
- **THEN** the Argus incident stays `resolved`

### Requirement: A failed read is retried by the platform, not lost

The system SHALL answer `503` when the platform cannot be read while a
person's resolution is being matched, so that the platform delivers it again.
It SHALL answer every other verified delivery with a success status.

#### Scenario: The platform is unreachable mid-match

- **GIVEN** a verified delivery of a person's resolution
- **WHEN** the platform's API cannot be read
- **THEN** the delivery is answered `503`, and no incident changes
