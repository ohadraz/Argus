## ADDED Requirements

### Requirement: The declared set admits an action that removes a derived copy

The declared set of generic mitigations SHALL include discarding named cache
entries, and that membership SHALL rest on the same criterion as every other
member's: the kind is declared, closed and read in one sitting.

The set now holds one of each shape - putting something back, adding something,
stopping something, and removing something - and the criterion has not moved for
any of them. What is said here is said because the fourth shape is the one most
likely to be mistaken for a weakening: an action that destroys a copy sounds
heavier than one that restores a value, and is not, because what it destroys is
derived from something it cannot reach.

#### Scenario: A discard of named entries is admitted
- **GIVEN** a proposed discard of cache entries named by the evidence
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, because the kind is in the declared set

#### Scenario: Membership is still the whole criterion
- **GIVEN** the discard's place in the set
- **WHEN** what admitted it is read
- **THEN** it is membership of the set, and not that the change could be put back
  or that it restores anything

### Requirement: An action whose change needs no undo records that it needs none

The system SHALL record, for an action that carries no undo descriptor, that none
is owed rather than that none was found, and SHALL distinguish the two wherever an
attempt is reported.

An undo descriptor has never been what permits an action, and its absence has
meant one thing until now: the action's kind has nothing to put back because the
change is not a value Argus set. A discard adds a second meaning - the change *was*
a removal, and recreating what was removed would recreate the incident - and a
reader of an unwound attempt needs to be able to tell "there was nothing to undo"
from "the undo was skipped".

#### Scenario: An attempt that needs no undo says so
- **GIVEN** an attempt whose action was a discard
- **WHEN** it is unwound after a refutation or a withdrawal
- **THEN** no write is made, and the record says the action needed no undo

#### Scenario: A missing undo is not reported as a failed one
- **GIVEN** an attempt whose action needed no undo
- **WHEN** the attempt is read back
- **THEN** nothing in it reads as an undo that could not be performed
