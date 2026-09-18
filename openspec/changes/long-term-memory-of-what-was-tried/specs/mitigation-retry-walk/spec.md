## ADDED Requirements

### Requirement: Candidate order is informed by what was tried before

Before the first action of an incident is proposed, the system SHALL search
long-term memory for records of similar past incidents, and SHALL demote any
candidate whose subject was acted on in one of them and refuted. Candidates not
named by any such record SHALL keep their confidence order among themselves.

The search happens once, before the order is fixed, rather than being offered as
something to ask for. A past refutation is not a hypothesis and the walk does
not reason about it - it is an ordering fact, and the walk that consults it every
time is the only one whose behaviour with memory and without it can be compared.

#### Scenario: A subject refuted on a similar incident is tried later

- **GIVEN** an incident with two candidates, the higher-confidence one naming a
  flag that a similar past incident acted on and refuted
- **WHEN** the candidate order is fixed
- **THEN** the other candidate is tried first

#### Scenario: A subject confirmed on a similar incident keeps its place

- **GIVEN** a candidate naming a flag that a similar past incident acted on and
  confirmed
- **WHEN** the candidate order is fixed
- **THEN** it is not demoted

#### Scenario: Candidates untouched by memory keep confidence order

- **GIVEN** three candidates, none named by any past record
- **WHEN** the candidate order is fixed
- **THEN** they are tried in descending confidence order, as they would be with
  no memory at all

### Requirement: Memory demotes a candidate but never removes it

A past refutation SHALL NOT mark a candidate tested, exclude it from the walk, or
prevent it from being tried when every candidate above it has been refuted. Where
memory demotes every candidate, the walk SHALL try them all, in the order memory
gave.

A past incident is evidence about a past incident. The same flag can break the
service twice, and a walk that refused to try the only candidate it had - on the
strength of a different incident's result - would end with an escalation it had
the means to avoid.

#### Scenario: A demoted candidate is still tried in its turn

- **GIVEN** two candidates where memory demoted the first
- **WHEN** the second is tried and refuted
- **THEN** the demoted candidate is tried next

#### Scenario: Every candidate demoted still yields a walk

- **GIVEN** an incident whose every candidate was refuted on similar past
  incidents
- **WHEN** the candidate order is fixed
- **THEN** the walk proceeds and the first of them is tried

### Requirement: The order memory produced is recorded

The incident's timeline SHALL record that memory changed the order candidates
would otherwise have been tried in, naming the past incident whose record caused
the change.

A walk that tried its second-best candidate first, with nothing saying why, is a
walk a human reading the incident back cannot account for.

#### Scenario: A reordering is accounted for

- **GIVEN** an incident where memory demoted the highest-confidence candidate
- **WHEN** the incident is read back
- **THEN** the timeline says the order was changed, and names the past incident
  it was changed on the strength of

#### Scenario: An unchanged order says nothing

- **GIVEN** an incident where memory named none of the candidates
- **WHEN** the incident is read back
- **THEN** the timeline records no reordering
