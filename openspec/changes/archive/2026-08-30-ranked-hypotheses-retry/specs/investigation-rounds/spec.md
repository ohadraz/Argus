## ADDED Requirements

### Requirement: A spent round buys a wider look, not a repeat
When every candidate above the mitigate threshold has been tried and refuted, and the widening schedule has not reached its maximum, the system SHALL investigate again, resuming the schedule from where the previous round stopped. The Investigator SHALL NOT restart from the initial lookback: evidence already read is not evidence worth paying for twice.

#### Scenario: The second round reads further back than the first
- **GIVEN** a first round that stopped confident at the schedule's first lookback
- **WHEN** every candidate it named is refuted
- **THEN** the next round's log window uses the schedule's next lookback

#### Scenario: Candidates from the cheap window are all tried before widening
- **GIVEN** a first round naming two candidates above the threshold
- **WHEN** the first is refuted
- **THEN** the second is tried before any wider investigation is run

### Requirement: Refutations are carried into the next round as evidence
A resumed investigation SHALL be given what was already tried and what it did, as part of the evidence the model reasons over. It SHALL be stated as fact - the change made, when, and that the service did not return to baseline - rather than as an instruction about what to avoid.

#### Scenario: The next round is told what failed
- **GIVEN** a refuted attempt that set a named flag off
- **WHEN** the next round's evidence is built
- **THEN** it names that flag, the state it was set to, and that the service did not recover

#### Scenario: A round that only repeats a refuted candidate yields nothing new
- **GIVEN** a resumed round whose every candidate has already been tried and refuted
- **WHEN** the candidates are filtered against what was tried
- **THEN** no untried candidate remains for that round

### Requirement: The walk terminates when nothing new is available
The walk SHALL end when a round produces no untried candidate above the mitigate threshold **and** the widening schedule has reached its maximum. Neither condition alone SHALL end it: a spent round with budget remaining SHALL widen, and a schedule at its maximum that still names something untried SHALL try it.

#### Scenario: Budget remains, so the walk widens rather than ending
- **GIVEN** a spent round and a schedule short of its maximum
- **WHEN** the walk decides what to do next
- **THEN** it investigates again rather than escalating

#### Scenario: The schedule is spent and nothing is untried, so the walk ends
- **GIVEN** a round at the schedule's maximum naming only candidates already refuted
- **WHEN** the walk decides what to do next
- **THEN** the incident escalates and a human is paged

#### Scenario: The schedule is spent but a new candidate appears
- **GIVEN** a round at the schedule's maximum naming one candidate never tried
- **WHEN** the walk decides what to do next
- **THEN** that candidate is tried

### Requirement: The walk has no attempt cap
The system SHALL NOT limit the number of attempts by a configured count. The candidate set is bounded by the evidence and the number of rounds is bounded by the widening schedule, so the walk is finite by construction.

#### Scenario: A long walk is not cut short
- **GIVEN** an incident whose rounds keep naming untried candidates within the schedule
- **WHEN** the walk runs
- **THEN** every such candidate is tried, and the walk ends only on the terminus above
