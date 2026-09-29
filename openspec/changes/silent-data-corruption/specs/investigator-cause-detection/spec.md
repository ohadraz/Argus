## ADDED Requirements

### Requirement: Silent data corruption is a determinable mode

The system SHALL admit `silent-data-corruption` as a failure mode the
Investigator can name: what a service has already written is wrong, while the
service itself is available, fast and reporting nothing.

It is separated from every other mode by what carries the evidence rather than by
what the evidence shows. No series departs, no log line reports a failure, and no
retrieval channel describes the fault at all - the whole of the symptom is a
reconciliation finding stated in the alert, and the whole of the investigation is
what changed around the minute that finding dates.

It is separated from a bad deployment and a flag toggle - which it may share a
cause with - by the damage outliving the change. There, removing the change ends
the incident; here, removing the change stops the drift and leaves every wrong
value where it was.

#### Scenario: A flat window with a reconciliation finding is named as corruption
- **GIVEN** an incident whose alert reports totals that do not reconcile, whose
  series are all at baseline, and whose change history holds a flag change at the
  stated onset
- **WHEN** the cause is determined
- **THEN** the mode is `silent-data-corruption`

#### Scenario: The cause is looked for at the stated onset, not at the alert
- **GIVEN** an incident whose alert fired a week after the onset it states
- **WHEN** the investigation reads what changed
- **THEN** it reads the flag and deploy histories around the stated onset

#### Scenario: A flat window with no finding is not named as corruption
- **GIVEN** an incident whose series are all at baseline and whose alert reports
  no reconciliation finding
- **WHEN** the cause is determined
- **THEN** the mode is not `silent-data-corruption`
