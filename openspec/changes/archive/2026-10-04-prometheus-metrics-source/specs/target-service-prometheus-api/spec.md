## ADDED Requirements

### Requirement: The Target Service stands in for Prometheus's range-query API
The Target Service SHALL serve `GET /prometheus/api/v1/query_range`, taking
`query`, `start`, `end` and `step` as Prometheus does, and answering in
Prometheus's envelope (`status`, `data.resultType` of `matrix`, `data.result`)
from the same minutes `GET /scenario/metrics` reports, value for value. It
SHALL answer the fixed set of queries Argus's adapter sends, and nothing more.

#### Scenario: A known query is answered as a matrix
- **GIVEN** a scenario is active
- **WHEN** `GET /prometheus/api/v1/query_range` is requested with one of
  Argus's queries and a window over minutes the scenario covers
- **THEN** it answers `"status": "success"` with a `matrix` whose samples are
  that field's values for those minutes, as `[unix_seconds, "value"]` pairs

#### Scenario: Values are those of the per-minute rows
- **GIVEN** a scenario is active
- **WHEN** each of Argus's queries is requested over the same window as
  `GET /scenario/metrics`
- **THEN** every sample equals the corresponding field of the corresponding
  row

#### Scenario: An unpublished minute has no sample
- **GIVEN** a scenario whose minute is unpublished, as in the blind-spot
  scenario
- **WHEN** a query covering that minute is requested
- **THEN** no series carries a sample for that minute

#### Scenario: An unknown query is Prometheus's bad_data
- **GIVEN** any state
- **WHEN** a query that is not one of Argus's is requested
- **THEN** it answers 400 with `"status": "error"` and `"errorType":
  "bad_data"`

#### Scenario: No active scenario is an empty matrix
- **GIVEN** no scenario is active
- **WHEN** any of Argus's queries is requested
- **THEN** it answers `"status": "success"` with an empty `result`

### Requirement: The stand-in's reporting lag is configurable
The stand-in SHALL take a reporting lag in minutes, 0 or 1. At 0 it SHALL
serve the unfinished minute, at the step that minute ends on; at 1 it SHALL
serve only minutes that have ended, as a source that reports a minute once it
is over.

#### Scenario: At lag 0 the unfinished minute is served
- **GIVEN** the reporting lag is 0 and a scenario is active
- **WHEN** a query is requested whose `end` is the end of the current minute
- **THEN** the result carries a sample for the current, unfinished minute

#### Scenario: At lag 1 the unfinished minute is withheld
- **GIVEN** the reporting lag is 1 and a scenario is active
- **WHEN** a query is requested whose `end` is the end of the current minute
- **THEN** the result carries no sample for the current, unfinished minute

### Requirement: The Target Service exposes its metrics in Prometheus text format
The Target Service SHALL serve `GET /metrics` as Prometheus text exposition
format (`Content-Type: text/plain; version=0.0.4`), carrying `# HELP` and
`# TYPE` lines and the current values of the series Argus's queries name.

#### Scenario: The scrape endpoint is text exposition
- **GIVEN** a scenario is active
- **WHEN** `GET /metrics` is requested
- **THEN** it answers `text/plain; version=0.0.4` with a `# TYPE` line for
  every series Argus's queries name
