## ADDED Requirements

### Requirement: An incident closed without its sight restored says so

The document SHALL say, where the metrics carry no minute at or after the
incident's onset when the postmortem is written, that the incident closed with
the service still unobserved, from which minute, and that the error rates cover
none of the minutes after it. The money is measured by the party that took it
and is unaffected. It SHALL NOT present the collected window
as the incident's duration.

#### Scenario: A still-blind incident is written up as still blind
- **GIVEN** an incident whose metrics stop at the onset and have not resumed when
  it ends
- **WHEN** the postmortem is written
- **THEN** it states that the service was still unobserved at close and names the
  minute the sight was lost

#### Scenario: A restored incident carries no such statement
- **GIVEN** an incident whose metrics resumed before it ended
- **WHEN** the postmortem is written
- **THEN** no statement of an unrestored sight appears
