## ADDED Requirements

### Requirement: A walk ended by a mode nothing answers is derived as `ESCALATED`

A walk whose mitigation phase ended because nothing answers the mode SHALL derive
`escalated` once Code-Fix has answered, whether or not it found a fix, and
`fixing` until then - the candidate it ended on is still the one in hand, and
is not under test. The symptom is still happening
and nothing Argus may do stops it; a proposal is what the incident carries, not
the state it is in. The derivation SHALL read a fact the walk records, never the
refusal's narration.

#### Scenario: Fixing until Code-Fix answers
- **GIVEN** a walk whose mitigation phase ended because nothing answers the mode,
  and which Code-Fix has not yet answered
- **WHEN** the status is derived
- **THEN** it is `fixing`

#### Scenario: Escalated with a fix
- **GIVEN** a walk whose mitigation phase ended because nothing answers the mode,
  and for which Code-Fix proposed a fix
- **WHEN** the status is derived
- **THEN** it is `escalated`

#### Scenario: Escalated without a fix
- **GIVEN** a walk whose mitigation phase ended because nothing answers the mode,
  and for which Code-Fix proposed nothing
- **WHEN** the status is derived
- **THEN** it is `escalated`
