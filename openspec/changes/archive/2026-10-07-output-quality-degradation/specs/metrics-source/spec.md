## ADDED Requirements

### Requirement: A window may carry one more query's values
The Prometheus adapter SHALL accept one additional PromQL query beside its fixed ones and, when
given one, SHALL carry its value for each minute on that minute's bucket. A minute the additional
query has no value for SHALL still be returned with its fixed fields, and an additional query
Prometheus refuses SHALL leave every minute without it rather than failing the window.

#### Scenario: The additional query's values ride on the buckets
- **GIVEN** an additional query Prometheus answers for every minute of a window
- **WHEN** the adapter is asked for that window with it
- **THEN** every bucket carries the query's value for its minute

#### Scenario: A refused additional query does not cost the window
- **GIVEN** an additional query Prometheus answers with `bad_data`
- **WHEN** the adapter is asked for a window with it
- **THEN** the buckets are returned with their fixed fields and no additional value
