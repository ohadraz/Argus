## ADDED Requirements

### Requirement: A mode nothing answers ends the mitigation phase

The walk SHALL go on to Code-Fix when the gate refuses a candidate because no
mitigation answers its mode. It SHALL NOT pass to the next candidate and SHALL
NOT spend its remaining investigation rounds.

A candidate reached in the walk is the most likely explanation still standing.
Where that explanation says no mitigation applies, a lower-ranked one that does
admit a mitigation is a less likely reading of the same evidence, and acting on
it is acting against the diagnosis. Further rounds would re-read the same
evidence and arrive at the same mode.

#### Scenario: A refused mode is not followed by the next candidate
- **GIVEN** an incident whose leading candidate is a mode no strategy answers,
  and whose second candidate is one a rollback answers
- **WHEN** the gate refuses the leading candidate
- **THEN** no action is proposed for the second candidate, and the walk goes to
  Code-Fix

#### Scenario: No further round is spent
- **GIVEN** an incident with rounds remaining
- **WHEN** the gate refuses a candidate because nothing answers its mode
- **THEN** the Investigator is not asked again
