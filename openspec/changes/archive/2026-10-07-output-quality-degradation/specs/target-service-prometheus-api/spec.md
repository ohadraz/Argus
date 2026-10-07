## MODIFIED Requirements

### Requirement: The Target Service stands in for Prometheus's range-query API
The Target Service SHALL serve `GET /prometheus/api/v1/query_range`, taking
`query`, `start`, `end` and `step` as Prometheus does, and answering in
Prometheus's envelope (`status`, `data.resultType` of `matrix`, `data.result`)
from the same minutes `GET /scenario/metrics` reports, value for value. It
SHALL answer the fixed set of queries Argus's adapter sends and every query a
rule definition names, and nothing more.

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

#### Scenario: A rule's query is answered
- **GIVEN** a scenario is active
- **WHEN** a query a rule definition names is requested
- **THEN** it answers with the series the rule is evaluated over

#### Scenario: An unpublished minute has no sample
- **GIVEN** a scenario whose minute is unpublished, as in the blind-spot
  scenario
- **WHEN** a query covering that minute is requested
- **THEN** no series carries a sample for that minute

#### Scenario: An unknown query is Prometheus's bad_data
- **GIVEN** any state
- **WHEN** a query that is neither one of Argus's nor one a rule definition names
  is requested
- **THEN** it answers 400 with `"status": "error"` and `"errorType":
  "bad_data"`

#### Scenario: No active scenario is an empty matrix
- **GIVEN** no scenario is active
- **WHEN** any of Argus's queries is requested
- **THEN** it answers `"status": "success"` with an empty `result`
