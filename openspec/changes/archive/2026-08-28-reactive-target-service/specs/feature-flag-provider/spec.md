## ADDED Requirements

### Requirement: A real feature-flag provider runs in the stack
The system SHALL run a self-hosted feature-flag provider as its own service in
the compose stack, exposing an administrative UI and an HTTP API for both
evaluating and changing flag state. The provider SHALL persist its state in the
stack's existing database server, in a database of its own, rather than
introducing a second database server.

#### Scenario: The provider is reachable once the stack is up
- **WHEN** the compose stack reports the flag provider healthy
- **THEN** its HTTP API answers requests and its administrative UI is reachable
  in a browser

#### Scenario: The provider's database is created with the stack
- **GIVEN** a stack brought up from empty volumes
- **WHEN** the flag provider starts
- **THEN** its database exists in the stack's existing database server and it
  completes its own schema setup without manual intervention

#### Scenario: Dependents wait for the provider
- **GIVEN** the flag provider takes longer to become healthy than the services
  that read from it
- **WHEN** the stack is brought up
- **THEN** the Target Service does not begin serving until the provider is
  healthy, or retries its provider calls until they succeed, rather than
  crashing

### Requirement: API credentials are provisioned without manual steps
The system SHALL provision the API credentials it needs - one able to evaluate
flags and one able to change them - as part of bringing the stack up, so that no
human has to log into the provider's UI before the stack is usable.

#### Scenario: A freshly created stack needs no console visit
- **GIVEN** a stack brought up from empty volumes
- **WHEN** the Target Service evaluates a flag and scenario control changes one
- **THEN** both succeed using credentials that were provisioned at startup

### Requirement: The Target Service bootstraps its flag at startup
The Target Service SHALL ensure, at startup, that the flag its checkout path
reads exists in the provider, is scoped to the environment being used, and
carries a rollout strategy that makes it evaluate true whenever its environment
is enabled. Creating the flag without such a strategy SHALL NOT be treated as
success.

#### Scenario: A missing flag is created
- **GIVEN** the provider has no flag by the configured name
- **WHEN** the Target Service starts
- **THEN** the flag exists afterwards, together with a rollout strategy covering
  every request

#### Scenario: An existing flag is left alone
- **GIVEN** the flag already exists in the provider
- **WHEN** the Target Service starts
- **THEN** the flag's configuration is unchanged and startup succeeds

#### Scenario: An enabled flag actually evaluates true
- **GIVEN** the Target Service has bootstrapped its flag
- **WHEN** the flag's environment is enabled and the Target Service evaluates it
- **THEN** the evaluation returns true

### Requirement: The Target Service evaluates flag state per request
The Target Service SHALL read flag state from the provider over HTTP at the time
it needs it, rather than from a cached copy refreshed on a timer, so that a
change made by any party is reflected in the Target Service's next response.

#### Scenario: A change made outside the Target Service is seen
- **GIVEN** the flag is enabled and the Target Service has served a request
  reflecting that
- **WHEN** the flag is disabled through the provider's own UI, by no action of
  the Target Service
- **THEN** the Target Service's next response reflects the flag being off

#### Scenario: An unreachable provider is not read as "off"
- **GIVEN** the flag provider cannot be reached
- **WHEN** the Target Service needs the flag's value
- **THEN** it reports the failure rather than substituting a default value that
  would read as a healthy service
