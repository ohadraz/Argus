## ADDED Requirements

### Requirement: The evidence shows the paging rule's series
The page's metrics evidence SHALL show the paging rule's series as a column of its
own beside the fixed signals, where an incident's metrics carry it, and the
narration of the metrics SHALL include it. Where they carry none, no such column
SHALL be shown.

#### Scenario: A quality incident's evidence shows the quality series
- **GIVEN** an incident whose metrics carry the rule's series
- **WHEN** its evidence is viewed
- **THEN** each minute shows the rule's series beside its error rate and
  latencies
