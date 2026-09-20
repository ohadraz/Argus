# cache-misconfiguration-scenario Specification

## Purpose
The Target Service staging an incident whose cause is a configuration value: a
deploy moves the cache's endpoint, every lookup is refused, every page
recomputes and every page is still correct. It is the one incident that lives
entirely in the median - the tail always described the recomputed path - so a
monitor watching p95 never sees it happen.
## Requirements

### Requirement: The cache is a real read in the service's own source
The Target Service SHALL render the account page partly from a cache it reads
before recomputing - the rendered spend summary, looked up by shopper - so that
the cache sits on the request path in source rather than in a fixture. The
lookup SHALL be made through a seam the generator can answer without a network
round trip, because the window's metrics are produced by rendering the page many
times a minute. No cache server SHALL be required to run.

#### Scenario: The page consults the cache before computing
- **GIVEN** an account page rendered for a shopper whose summary is cached
- **WHEN** the page is served
- **THEN** the summary comes from the cache and is not recomputed

#### Scenario: A miss is recomputed rather than failed
- **GIVEN** an account page rendered for a shopper whose summary is not cached
- **WHEN** the page is served
- **THEN** the summary is computed from the shopper's purchases and the page
  succeeds

### Requirement: The cache endpoint is read from deployment configuration
The Target Service SHALL read the cache's endpoint - its host and port - from
deployment configuration held in a values file in the repository, rather than
from a constant in the source. The file SHALL be the one a deployment would
actually carry, so that changing the endpoint is a change to configuration and
not to code, and so that the change is visible as a diff between two commits.

#### Scenario: The port is found in the values file and not in the source
- **GIVEN** the repository at the seeded commit
- **WHEN** the cache endpoint's port is looked for
- **THEN** it is in the deployment values file, and no port is written in the
  service's source

#### Scenario: The change is a one-line diff between two commits
- **GIVEN** the commit that staged the incident and its parent
- **WHEN** the two are diffed
- **THEN** the difference is the cache port in the values file and nothing else

### Requirement: An unreachable cache degrades the shop without failing it
The Target Service SHALL compute a minute's telemetry from whether the
configured endpoint is reachable. While it is not, every lookup SHALL fail to
connect and every page SHALL recompute, so that latency departs its baseline
while the error rate stays at baseline and memory stays flat. The shop SHALL go
on serving correct pages throughout - the fallback is the designed behaviour,
and an incident in which nothing fails is the property this scenario exists to
demonstrate.

#### Scenario: Latency departs while errors and memory do not
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** a window spanning the onset is retrieved
- **THEN** latency departs its baseline, and `error_rate` and
  `memory_used_bytes` stay at theirs

#### Scenario: Pages are still correct while the cache is unreachable
- **GIVEN** the cache endpoint is unreachable
- **WHEN** an account page is served
- **THEN** it renders the same summary it would have rendered from the cache

### Requirement: The tail does not show this incident and the median does
The Target Service SHALL stage the cache condition so that `p95_ms` barely
departs its baseline while `p50_ms` departs it steeply. The hit ratio SHALL
leave the tail already describing a recomputed request before the onset, so
that losing the cache moves the tail from one miss to another while moving the
median from the cached path to the recomputed one.

This is the property the scenario exists for. An incident visible in the
aggregate a system watches most confidently is an incident that system was
always going to find; this one is legible only in the quantile that reports
what a typical shopper actually experienced, which is the case that says
whether reading the tail alone is enough.

#### Scenario: The median departs and the tail does not
- **GIVEN** a window spanning the onset
- **WHEN** the departure in each latency quantile is measured
- **THEN** `p50_ms` has departed its baseline by a wide margin and `p95_ms` has
  not departed appreciably

#### Scenario: The incident is found despite the tail being quiet
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** the onset is located from the metrics
- **THEN** it is the minute the cache became unreachable

### Requirement: The hit ratio is reported on every minute of every scenario
The Target Service SHALL report the share of lookups served from the cache on
every generated minute, whether or not the seeded scenario concerns the cache. A
field that appeared only when it mattered would be a signal by its presence, and
a baseline nobody can see is not a baseline.

#### Scenario: A scenario about something else still reports a hit ratio
- **GIVEN** a seeded scenario that stages no cache condition
- **WHEN** a metrics window is retrieved
- **THEN** every bucket reports a hit ratio at the healthy baseline

#### Scenario: The ratio falls to nothing while the endpoint is unreachable
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** a window spanning the onset is retrieved
- **THEN** the hit ratio is at its baseline before the onset and at zero after it

### Requirement: The service says which endpoint it could not reach
The Target Service SHALL emit a log line naming the endpoint it failed to
connect to, including the port, at the density its other failure lines are
emitted at. The line SHALL report the connection failure as the service
observed it and SHALL NOT name a cause, a deploy or a configuration change -
joining the endpoint to the change that produced it is the reader's inference.

#### Scenario: The failing endpoint is named in the logs
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** the logs for a window after the onset are retrieved
- **THEN** they carry a connection-failure line naming the configured host and
  port

#### Scenario: The logs do not name the deploy
- **WHEN** the logs for any window of the scenario are retrieved
- **THEN** no line mentions a deployment, a revision or a configuration change

### Requirement: A generated scenario can carry a deploy
The Target Service SHALL report a revision history for a generated scenario that
stages a deploy, rather than treating every generated scenario as having none.
The deploy SHALL name the commit that changed the values file, so that a reader
asking what changed is given the revision whose diff holds the answer.

#### Scenario: The config deploy appears in the revision history
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** the application's revision history is retrieved
- **THEN** it carries a deploy at the onset minute, naming the commit that
  changed the values file

#### Scenario: A generated scenario staging no deploy still reports none
- **GIVEN** a seeded scenario that stages no deploy
- **WHEN** the application's revision history is retrieved
- **THEN** it is empty

### Requirement: The incident ends when the endpoint is reachable again
The Target Service SHALL end the incident when the configured endpoint is put
back, whoever puts it back and by whatever route - so that a mitigation attempt
can be honestly graded. Rolling the deployment back SHALL restore the endpoint;
restarting the service SHALL NOT, because the process comes back up reading the
same configuration.

#### Scenario: A rollback ends the incident
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** the deployment is rolled back to the revision before the change
- **THEN** the hit ratio returns to its baseline and latency subsides

#### Scenario: A restart does not end the incident
- **GIVEN** a seeded cache-misconfiguration scenario
- **WHEN** the service is restarted
- **THEN** the process start time changes and the latency stays where it was
