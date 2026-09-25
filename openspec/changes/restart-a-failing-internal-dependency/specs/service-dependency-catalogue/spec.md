## ADDED Requirements

### Requirement: What a service calls is retrievable as evidence
The system SHALL offer, on the read tier, a tool answering what a named service
depends on: each dependency's name, what the calling service uses it for, and
whether the organisation owns it. The answer SHALL reach the model typed, as
every other channel does, rather than as prose the model parses.

This is a channel and not configuration. Argus's own settings naming the
topology would hardcode one deployment's answer into the agent - the objection
the restart strategy already makes about its own subject - and, worse, would put
the ownership fact out of the Investigator's reach, when ownership is the one
thing that tells an internal dependency's failure from a third party's.

#### Scenario: A service's dependencies are returned with their ownership
- **GIVEN** a service that calls one dependency the organisation owns and one it
  does not
- **WHEN** the catalogue is read for that service
- **THEN** both are returned, each with what it is for, and each marked as owned
  or not owned

#### Scenario: A service with nothing recorded answers empty rather than failing
- **GIVEN** a service the catalogue holds no entry for
- **WHEN** the catalogue is read for it
- **THEN** it answers with no dependencies, and the caller can tell that from an
  error

### Requirement: The catalogue is the evidence that separates an internal dependency from a third party
The system SHALL make ownership readable for every dependency a scenario puts on
the request path, including the ones that stage a third party's failure. An
incident in which the caller's own logs blame something else SHALL be
distinguishable - between a failure to escalate and a failure to act on - by the
catalogue rather than by inference from the dependency's name.

#### Scenario: A third party's failure is identifiable as a third party's
- **GIVEN** an incident whose logs attribute the failure to a dependency the
  catalogue marks as not owned
- **WHEN** the evidence is weighed
- **THEN** ownership is available as retrieved evidence, and the conclusion does
  not rest on the dependency's name

#### Scenario: An owned dependency is identifiable as one
- **GIVEN** an incident whose logs attribute the failure to a dependency the
  catalogue marks as owned
- **WHEN** the evidence is weighed
- **THEN** ownership is available as retrieved evidence

### Requirement: The catalogue is carried into the autonomy gate as a value
The system SHALL hand the catalogue to the autonomy gate as a value retrieved
beforehand, never fetched while an action is being judged. Whether Argus may act
SHALL NOT depend on the catalogue being reachable at that moment.

The gate is what weighs ownership, and the strategy that proposes the action is
not: a strategy reads the address the investigation wrote down, and whether that
address may be touched is a question about authority rather than about which
mitigation answers a cause.

#### Scenario: The gate judges from values already in hand
- **GIVEN** an incident whose proposed action is being judged
- **WHEN** the gate weighs where the action is addressed
- **THEN** the catalogue it weighs against was retrieved before the action was
  proposed, and no retrieval happens inside the gate
