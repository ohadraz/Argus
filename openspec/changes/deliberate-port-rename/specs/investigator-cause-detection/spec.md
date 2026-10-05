## ADDED Requirements

### Requirement: Monitoring configuration drift is a determinable mode

The system SHALL admit `monitoring-configuration-drift` as a failure mode the
Investigator can name: the service was deliberately changed and is well, and the
configuration that observes it was not changed with it.

The evidence SHALL be a blind spot's four facts - an absence alert, a window that
stops at the onset, logs answering across it, a change at the onset - with the
change being one that applies a rule rather than one that alters a single value.
Which of the two a change is SHALL be read from the diff, never from a commit
message or any other channel the Investigator does not read.

#### Scenario: A blind spot whose change applies a convention is drift
- **GIVEN** a blind spot's evidence, whose change renames every port in the
  deployment to one convention
- **WHEN** the cause is determined
- **THEN** the mode named is `monitoring-configuration-drift`

#### Scenario: A blind spot whose change is a lone rename stays a blind spot
- **GIVEN** a blind spot's evidence, whose change renames the metrics port alone
- **WHEN** the cause is determined
- **THEN** the mode named is `monitoring-blind-spot`

### Requirement: Drift is separated from the modes it most resembles

The mode's meaning SHALL separate it from `monitoring-blind-spot`, whose change
was a mistake and is answered by returning it, and from `config-induced-failure`,
whose broken configuration is the service's own. Here the service's configuration
is the intended one and the observer's is behind it, so what is owed is a change
to the observer rather than to the service.

#### Scenario: The meaning names what is owed
- **WHEN** the mode's meaning is read
- **THEN** it says the observer's configuration is rolled forward and the
  service's change is kept
