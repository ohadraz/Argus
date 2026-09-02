## MODIFIED Requirements

### Requirement: A spent round buys a wider look, not a repeat
When every candidate above the mitigate threshold has been tried and refuted, and the walk has not exhausted its configured rounds, the system SHALL investigate again. The next round SHALL be given what the previous rounds read and what their attempts did, so that it is asking a different question rather than paying again for the same one. The Investigator SHALL NOT be told which window to use: what makes the round new is the refutations it carries, not a scheduled position it resumes from.

#### Scenario: The second round is told what the first one read
- **GIVEN** a first round that answered from a log window around the onset
- **WHEN** every candidate it named is refuted
- **THEN** the next round's opening message names the windows already read and the
  attempts that failed

#### Scenario: Candidates from the first round are all tried before investigating again
- **GIVEN** a first round naming two candidates above the threshold
- **WHEN** the first is refuted
- **THEN** the second is tried before any further investigation is run

### Requirement: The walk terminates when nothing new is available
The walk SHALL end when a round produces no untried candidate above the mitigate threshold **and** the configured round budget is spent. Neither condition alone SHALL end it: a spent round with rounds remaining SHALL investigate again, and a spent round budget that still names something untried SHALL try it.

#### Scenario: Rounds remain, so the walk investigates again rather than ending
- **GIVEN** a spent round and a round budget not yet exhausted
- **WHEN** the walk decides what to do next
- **THEN** it investigates again rather than escalating

#### Scenario: The round budget is spent and nothing is untried, so the walk ends
- **GIVEN** a final round naming only candidates already refuted
- **WHEN** the walk decides what to do next
- **THEN** the incident escalates and a human is paged

#### Scenario: The round budget is spent but a new candidate appears
- **GIVEN** a final round naming one candidate never tried
- **WHEN** the walk decides what to do next
- **THEN** that candidate is tried

### Requirement: The walk has no attempt cap
The system SHALL NOT limit the number of attempts by a configured count. The candidate set is bounded by the evidence and the number of rounds is bounded by the configured round budget, so the walk is finite by construction.

#### Scenario: A long walk is not cut short
- **GIVEN** an incident whose rounds keep naming untried candidates within the round budget
- **WHEN** the walk runs
- **THEN** every such candidate is tried, and the walk ends only on the terminus above
