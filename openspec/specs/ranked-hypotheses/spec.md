# ranked-hypotheses Specification

## Purpose
TBD - created by archiving change ranked-hypotheses-retry. Update Purpose after archive.
## Requirements
### Requirement: An investigation yields candidates in confidence order
The Investigator SHALL return an ordered list of candidate hypotheses rather than a single hypothesis. The order SHALL be by descending confidence, with ties keeping the order the model gave. Every candidate SHALL be a complete hypothesis in its own right - summary, cause type, confidence, supporting evidence, and subject where the cause names one.

#### Scenario: Several explanations are returned best-first
- **WHEN** the model's verdict names a cause at 0.82 and an alternative at 0.61
- **THEN** the investigation returns two candidates, the 0.82 one first

#### Scenario: A verdict with no alternatives yields one candidate
- **WHEN** the model's verdict names a cause and no alternatives
- **THEN** the investigation returns exactly one candidate, and nothing about the consuming path differs from a single-hypothesis investigation

#### Scenario: The model's ordering does not override its own confidences
- **WHEN** the model lists an alternative at 0.90 after its primary answer at 0.70
- **THEN** the 0.90 candidate is ranked first

### Requirement: Every candidate is recorded, and only confident ones are acted on
The system SHALL persist every candidate as its own `hypothesis` row carrying its rank. Only candidates whose confidence meets the mitigate threshold SHALL be eligible for mitigation; the rest SHALL be recorded and left untried, so a human reading the incident sees what was considered as well as what was attempted.

#### Scenario: A sub-threshold candidate is recorded but never acted on
- **GIVEN** an investigation returning candidates at 0.81 and 0.40, with a mitigate threshold of 0.75
- **WHEN** the walk runs
- **THEN** both candidates are on the incident, and only the 0.81 one has an action taken for it

#### Scenario: No candidate above the threshold escalates
- **GIVEN** an investigation whose every candidate is below the mitigate threshold
- **WHEN** the graph runs
- **THEN** no action is taken and the incident escalates, as it does for a single unconfident hypothesis today

### Requirement: An investigation always reports what it concluded
The candidate list SHALL never be empty: an investigation that identified no cause reports that as its one candidate, carrying the reason nothing was found. Whether anything on the list is worth acting on SHALL be decided by confidence against the mitigate threshold, not by the list's length.

"Nothing to try" is therefore expressed the way it already is - a candidate no confidence supports - rather than by an absence. An empty list would leave the reason nothing was found without a place to live, and would state in a second way something the threshold already states.

#### Scenario: No cause determined
- **WHEN** the evidence identifies no cause
- **THEN** the investigation reports one candidate naming no cause and carrying the reason, no action is taken, and the incident escalates

#### Scenario: A walk never begins on an unactionable list
- **GIVEN** an investigation whose only candidate names no cause
- **WHEN** the walk decides what to try
- **THEN** it finds nothing above the mitigate threshold and tries nothing

