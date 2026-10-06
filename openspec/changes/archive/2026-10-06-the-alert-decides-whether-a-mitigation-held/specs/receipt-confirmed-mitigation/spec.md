## MODIFIED Requirements

### Requirement: A flat window may not confirm an action that carries no receipt

The system SHALL treat an attempt as unconfirmed where the window holds no departure
to have recovered from and the action performed reports nothing about what it changed,
unless the alert rule that paged judges the attempt, in which case the window reaches no
verdict of its own.

#### Scenario: A restart in a flat window is not confirmed
- **GIVEN** an incident whose onset the alert stated and whose window is flat
  throughout
- **WHEN** a restart is performed and the window is read afterwards
- **THEN** the attempt is not confirmed, and the walk is free to try its next
  candidate

#### Scenario: A discard in the same window is confirmed
- **GIVEN** the same incident
- **WHEN** a discard of named entries is performed and returns a count
- **THEN** the attempt is confirmed

#### Scenario: A measured onset is judged by the levels where no rule judges it
- **GIVEN** an incident whose onset was measured from its own series, and whose alert
  names no rule that paged
- **WHEN** any action is performed
- **THEN** the levels decide, whether or not the action carries a receipt

#### Scenario: A rule that paged judges in place of the window
- **GIVEN** an incident whose alert names the rule that paged
- **WHEN** any action is performed
- **THEN** the rule decides, and the window only dates the recovery

### Requirement: Which rule judged an attempt is recorded

The system SHALL record which of the four judgements settled an attempt, so that a
reader of the incident can tell a rule that stopped firing from a level that came down,
from a reading that returned, from an action that reported its own effect.

An attempt confirmed by a receipt is a weaker claim than one confirmed by a service
getting better, and the record SHALL not let the two read alike. What a receipt
establishes is that the change was made; what makes that sufficient here is the
nature of the change, which the incident's account states rather than implies.

#### Scenario: The record says the receipt settled it
- **GIVEN** an attempt confirmed from a discard's count
- **WHEN** the attempt is read back
- **THEN** it says it was confirmed by what the action reported, and what that
  report was

#### Scenario: The record says the levels settled it
- **GIVEN** an attempt confirmed by a series falling back
- **WHEN** the attempt is read back
- **THEN** it says so

#### Scenario: The record says the rule settled it
- **GIVEN** an attempt confirmed by the rule that paged stopping firing
- **WHEN** the attempt is read back
- **THEN** it says the rule that paged stopped firing
