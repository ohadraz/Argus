## ADDED Requirements

### Requirement: Metrics are read through a port, in Argus's own vocabulary
The system SHALL read a service's per-minute metrics through a `MetricsSource`
protocol that takes a window's two instants and returns `MetricBucket`s,
chronological, one per minute. No vendor's object, field name or error SHALL
reach anything above the adapter that implements it.

#### Scenario: A window's minutes come back as buckets
- **GIVEN** a source that holds minutes inside and outside a window
- **WHEN** the source is asked for that window
- **THEN** it returns one `MetricBucket` per minute inside the window, in
  chronological order, and none outside it

#### Scenario: An unreadable source is not an empty window
- **GIVEN** a source whose backend cannot be reached or answers with an error
- **WHEN** the source is asked for a window
- **THEN** it raises `MetricsUnavailable` rather than returning an empty list

### Requirement: Prometheus is read through its range-query API
The system SHALL provide a Prometheus adapter implementing `MetricsSource`
that sends `GET {prometheus_base_url}/api/v1/query_range` with `query`,
`start`, `end` and a `step` of one minute, one PromQL query per bucket field,
and SHALL translate the `matrix` results into `MetricBucket`s.
`prometheus_base_url` SHALL be a setting, so that the path after it is always
Prometheus's own.

#### Scenario: The request is Prometheus's
- **GIVEN** `prometheus_base_url` is `http://host:8080/prometheus`
- **WHEN** the adapter is asked for a window
- **THEN** every request it sends is `GET` to
  `http://host:8080/prometheus/api/v1/query_range` with `query`, `start`,
  `end` and `step=60s`

#### Scenario: The unfinished minute is asked for
- **GIVEN** a window whose end falls inside a minute
- **WHEN** the adapter is asked for that window
- **THEN** the `end` it sends is the end of that minute

#### Scenario: A matrix answer becomes buckets
- **GIVEN** Prometheus answers each query with a `matrix` whose samples cover
  the same minutes
- **WHEN** the adapter is asked for that window
- **THEN** each minute becomes one `MetricBucket` whose fields carry the
  sample values of the matching queries

#### Scenario: A minute missing a required series is not reported
- **GIVEN** Prometheus answers with no sample at some minute for a series a
  bucket requires
- **WHEN** the adapter is asked for a window containing that minute
- **THEN** no bucket is returned for that minute, rather than one reporting
  zero

#### Scenario: An optional series that is absent becomes None
- **GIVEN** Prometheus answers an empty result for a series a bucket holds as
  optional, such as the memory limit
- **WHEN** the adapter is asked for a window
- **THEN** the buckets carry `None` for that field

#### Scenario: Prometheus's error envelope is unavailability
- **GIVEN** Prometheus answers `"status": "error"` or a non-2xx status
- **WHEN** the adapter is asked for a window
- **THEN** it raises `MetricsUnavailable` carrying Prometheus's `errorType`
  and `error`
