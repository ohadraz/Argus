## ADDED Requirements

### Requirement: The paging rule's series is reported beside the error rate
Where the incident's metrics carry the paging rule's series, the postmortem SHALL
report that series' level before the onset, its mean while broken and its worst
in the direction its rule calls worse, computed from the metrics as every other
figure is, beside the error rate. Where they carry none, no such figure SHALL be
reported, rather than one of zero.

#### Scenario: A quality incident reports the quality series
- **GIVEN** an incident whose rule's series fell from about 0.95 to about 0.4
  while the error rate never moved
- **WHEN** the postmortem is written
- **THEN** it reports the series' baseline, its mean while broken and its lowest
  value, and the error rate as it was

#### Scenario: An incident with no rule's series reports none
- **GIVEN** an incident whose alert named no rule
- **WHEN** the postmortem is written
- **THEN** no rule-series figure appears in it
