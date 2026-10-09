## ADDED Requirements

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
