## ADDED Requirements

### Requirement: A disproven alarm is derived as `DISPROVEN`

The system SHALL derive `DISPROVEN` from a state whose investigation reported
that the alarm was disproven, and SHALL do so in the same pure function that
derives every other status - from the state, with no node permitted to set it.

`DISPROVEN` is not a kind of escalation. An escalation hands over an incident
nobody has explained; this hands over nothing, because the finding is that there
was no incident. The word is deliberately not `refuted`, which this system
already uses for a mitigation attempt the evidence undid.

#### Scenario: A disproven alarm yields disproven
- **GIVEN** a state whose investigation reported the alarm disproven
- **WHEN** the status is derived
- **THEN** it is `disproven`, and not `escalated`

#### Scenario: An investigation that found nothing is still escalated
- **GIVEN** a state whose investigation read its channels and reported no
  candidate worth trying, without disproving the alarm
- **WHEN** the status is derived
- **THEN** it is `escalated`, unchanged

#### Scenario: A withdrawn incident never reaches the question
- **GIVEN** an incident a human has withdrawn
- **WHEN** a node of the walk would run
- **THEN** the walk reports `withdrawn` without deriving a status at all, so no
  ending the walk could derive - this one included - can replace it
