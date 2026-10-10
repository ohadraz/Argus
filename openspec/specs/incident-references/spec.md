# incident-references

## Purpose

Covers the names external tools know an incident by: each recorded on the
incident as a source, a kind and a value, taken from the alert at intake and
added as other tools link to it, and the lookup that finds an incident from
any one of them. A new tool adds references, never columns on the incident.
## Requirements
### Requirement: Argus records what each tool calls an incident

The system SHALL record, for each incident, the names external tools know it
by, each as a source, a kind and a value. A value SHALL belong to at most one
incident per source and kind. A new tool SHALL add references, never columns on
the incident.

#### Scenario: A reference names one incident

- **GIVEN** a reference recorded for one incident
- **WHEN** the same source, kind and value is recorded for another
- **THEN** the first incident keeps it, and the second records nothing

### Requirement: Intake records the alert's references

The system SHALL record the references an alert carries when the alert opens
an incident, and also when it joins an open one. For a Grafana alert, it SHALL
record the key Grafana stamps on every notification it sends a paging tool:
the SHA-256 of the alert group's key. An alert without a group key SHALL be
accepted with no reference.

#### Scenario: A Grafana alert with a group key

- **WHEN** a Grafana alert with a group key opens an incident
- **THEN** the incident has a Grafana reference whose value is the SHA-256 of
  that group key

#### Scenario: A second alert group joins an open incident

- **GIVEN** an open incident for a rule and service
- **WHEN** an alert from a different group arrives for the same rule and service
- **THEN** that group's key is recorded on the same incident

#### Scenario: No group key

- **WHEN** a Grafana alert without a group key arrives
- **THEN** the incident opens with no reference

### Requirement: An incident is found by any of its references

The system SHALL find the incident that holds any of a set of reference values
of a given kind, and SHALL answer that none does when none matches.

#### Scenario: Found by one key among several

- **GIVEN** an incident with a reference of value `k`
- **WHEN** it is looked up by the values `x`, `k`
- **THEN** that incident is found

### Requirement: An incident's chat thread is one of its references

The system SHALL record the chat thread an incident is told in as one of the
incident's references, keyed by the channel and the thread's own identity, and
SHALL hold at most one thread per incident per channel. A second thread
recorded for the same incident and channel SHALL record nothing and leave the
first standing. A message received in a thread SHALL find its incident through
this reference.

#### Scenario: The first thread stands

- **GIVEN** an incident with a thread recorded in a channel
- **WHEN** a second thread is recorded for that incident in that channel
- **THEN** the first remains the incident's thread there

#### Scenario: A reply finds its incident

- **GIVEN** an incident with a thread recorded
- **WHEN** it is looked up by that channel and thread
- **THEN** that incident is found

### Requirement: A reference can be claimed once

The system SHALL record a reference and say whether this recording was the one
that wrote it, so that a delivery repeated by its sender is acted on once.

#### Scenario: A second claim

- **GIVEN** a reference already recorded
- **WHEN** it is claimed again
- **THEN** the claim reports that nothing was written

