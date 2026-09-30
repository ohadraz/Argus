## ADDED Requirements

### Requirement: A monitoring blind spot is a determinable mode

The system SHALL admit `monitoring-blind-spot` as a failure mode the
Investigator can name: the shop's own telemetry has stopped being published
while the shop is available, correct and fast.

It is the first mode whose subject is the monitoring rather than the thing
monitored, and the first whose correct reading of the evidence is *I cannot
see*. What is wrong is neither availability, speed, capacity nor what has been
written, but the ability to observe any of them.

The evidence that names it SHALL be four facts taken together, none of which
identifies it alone:

- an alert whose subject is an absence - a series that was reporting and
  stopped - rather than a threshold anything crossed;
- a metrics window whose rows stop at the stated onset, with nothing at or
  after that minute;
- a logs channel answering normally across those same minutes, which is what
  says the shop behind the missing rows is well;
- a change at the stated onset, which is what the incident is about.

#### Scenario: A window that stops under an absence alert is named as a blind spot
- **GIVEN** an incident whose alert reports that a series has stopped
  reporting, whose metrics carry no minute at or after the stated onset, whose
  logs answer normally across those minutes, and whose change history holds a
  flag change at that onset
- **WHEN** the cause is determined
- **THEN** the mode is `monitoring-blind-spot`

#### Scenario: A window that stops is not read as a healthy service
- **GIVEN** an incident whose metrics carry no minute at or after the stated
  onset
- **WHEN** the cause is determined
- **THEN** the absence is not concluded to mean the service is well, and the
  investigation does not end with nothing worth trying

#### Scenario: A window that was read throughout is not named as a blind spot
- **GIVEN** an incident whose metrics carry a bucket for every minute of the
  window, including the minutes at and after the stated onset
- **WHEN** the cause is determined
- **THEN** the mode is not `monitoring-blind-spot`

### Requirement: A blind spot is separated from the modes it most resembles

The mode SHALL be distinguished from three others by what the evidence is
rather than by what any action would be, because the action is the same as a
flag toggle's and the evidence is not.

**From `silent-data-corruption`**, which also has metrics carrying nothing
about the incident: there every minute is present and sitting at its baseline,
and the fault is in what was written. Here the minutes are missing, and nothing
the shop wrote is wrong. A flat window and an absent one are the two ways
metrics can fail to describe an incident, and they are not the same failure.

**From `feature-flag-toggle` and `bad-deployment`**, whose arrival and whose
action are both identical to this one's: there a series departs its baseline
because the shop got worse. Here no series departs, because no series exists
for the minutes in question, and the shop did not get worse at all. What
differs is whether the service or the sight of it degraded.

**From a metrics source that could not be read**, which is not this mode: there
the read fails, and Argus says which read it could not take. Here the read
succeeds and carries less than the truth. A channel that refused is a gap in
the evidence Argus reports; a channel that answered short is a gap it has to
notice.

Naming either of the first two in place of this one SHALL be understood to cost
something real, which is why the mode earns a value though it brings no new
action. Read as a flag toggle, the incident closes with a defect filed against
code that has none, and nothing records that the organisation spent that window
unable to see. Read as the shop being down, a healthy service is rolled back
and people are paged for it.

#### Scenario: A flat window with every minute present is not a blind spot
- **GIVEN** an incident whose metrics carry a bucket for every minute, all of
  them at baseline, under an alert reporting a reconciliation finding
- **WHEN** the cause is determined
- **THEN** the mode is not `monitoring-blind-spot`

#### Scenario: A departing series is not a blind spot
- **GIVEN** an incident whose metrics carry every minute and whose error rate
  departs its baseline at the onset, with a flag change at that minute
- **WHEN** the cause is determined
- **THEN** the mode is `feature-flag-toggle` rather than
  `monitoring-blind-spot`

#### Scenario: A read that could not be taken is not a blind spot
- **GIVEN** an incident whose metrics read failed rather than answering
- **WHEN** the incident's account is read
- **THEN** it says which read could not be taken, and no cause is named from
  the absence

### Requirement: The cause is sought at the minute the sight was lost

Where the mode is a blind spot, the investigation SHALL read what changed
around the stated onset - the minute the last sample arrived - rather than
around the minute the alert fired.

The two are deliberately far apart in this mode, because an absence has to be
held before it can be reported. A change history read around the firing would
cover minutes in which nothing happened, and would miss the change that stopped
the publishing by however long the rule waits.

The stated onset SHALL be the only source of that minute for this mode. It is
not a fallback for a measurement that failed: a measurement is impossible here
by construction, since the rows that would carry a departure are the ones that
are missing.

#### Scenario: The change history is read around the stated onset
- **GIVEN** an incident whose alert states the onset of an absence, having
  fired well after it
- **WHEN** the investigation reads what changed
- **THEN** it reads the flag and deploy histories around the stated onset

#### Scenario: The flag change at the onset is what the mode is about
- **GIVEN** an incident named as `monitoring-blind-spot`
- **WHEN** its subject is read
- **THEN** it names the flag whose change stopped the publishing
