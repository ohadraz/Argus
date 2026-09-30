## ADDED Requirements

### Requirement: A monitoring blind spot is a determinable mode

The system SHALL admit `monitoring-blind-spot` as a failure mode the
Investigator can name: the shop's own telemetry has stopped being collected
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
- a change at or after the stated onset, which is what the incident is about.

The fourth fact is the one that inverts a rule the rest of the taxonomy
teaches. Elsewhere a change is corroborated by the minutes around it: a
deployment at the onset is the suspect because the series departed there, and a
reader can watch the departure happen. Here the minutes around the change do
not exist - the change is what ended them - so the onset carries no reading of
its own and there is nothing at that minute to corroborate anything with. The
change is dated later than the last row that exists rather than later than the
onset, and a reader looking for the departure it caused finds an absence
instead.

#### Scenario: A window that stops under an absence alert is named as a blind spot
- **GIVEN** an incident whose alert reports that a series has stopped
  reporting, whose metrics carry no minute at or after the stated onset, whose
  logs answer normally across those minutes, and whose change history holds a
  deployment at or after that onset
- **WHEN** the cause is determined
- **THEN** the mode is `monitoring-blind-spot`

#### Scenario: A window that stops is not read as a healthy service
- **GIVEN** an incident whose metrics carry no minute at or after the stated
  onset
- **WHEN** the cause is determined
- **THEN** the absence is not concluded to mean the service is well, and the
  investigation does not end with nothing worth trying

#### Scenario: A change no reading corroborates is not ruled out for that
- **GIVEN** an incident whose metrics stop at the stated onset and whose only
  change landed at or after the last row the window carries
- **WHEN** the cause is determined
- **THEN** that change is weighed as the candidate rather than discarded for
  having no departure beside it

#### Scenario: A window that was read throughout is not named as a blind spot
- **GIVEN** an incident whose metrics carry a bucket for every minute of the
  window, including the minutes at and after the stated onset
- **WHEN** the cause is determined
- **THEN** the mode is not `monitoring-blind-spot`

### Requirement: A blind spot is separated from the modes it most resembles

The mode SHALL be distinguished from three others by what the evidence is
rather than by what any action would be, because the action is the same as a
bad deployment's and the evidence is not.

**From `silent-data-corruption`**, which also has metrics carrying nothing
about the incident: there every minute is present and sitting at its baseline,
and the fault is in what was written. Here the minutes are missing, and nothing
the shop wrote is wrong. A flat window and an absent one are the two ways
metrics can fail to describe an incident, and they are not the same failure.

**From `bad-deployment` and `config-induced-failure`**, which arrive exactly as
this one does - a revision at the onset, answered by returning it: there a
series departs its baseline because the shop got worse. Here no series departs,
because no series exists for the minutes in question, and the shop did not get
worse at all. What differs is whether the service or the sight of it degraded,
and the deploy history cannot say: it records that a revision was deployed and
never what the revision touched.

The service being visibly unchanged around the deployment SHALL be understood
as the mode's own prediction rather than as evidence the deployment was
innocent. Everywhere else a change that left the shop serving exactly as before
is grounds for acquitting it; here it is the thing being described.

**From a metrics source that could not be read**, which is not this mode: there
the read fails, and Argus says which read it could not take. Here the read
succeeds and carries less than the truth. A channel that refused is a gap in
the evidence Argus reports; a channel that answered short is a gap it has to
notice.

Naming either of the first two in place of this one SHALL be understood to cost
something real, which is why the mode earns a value though it brings no new
action. Read as a bad deployment, the incident closes with a defect filed
against code that has none, and nothing records that the organisation spent
that window unable to see - while the rollback, being the same call, succeeds
and makes the wrong account look confirmed.

#### Scenario: A flat window with every minute present is not a blind spot
- **GIVEN** an incident whose metrics carry a bucket for every minute, all of
  them at baseline, under an alert reporting a reconciliation finding
- **WHEN** the cause is determined
- **THEN** the mode is not `monitoring-blind-spot`

#### Scenario: A departing series is not a blind spot
- **GIVEN** an incident whose metrics carry every minute and whose error rate
  departs its baseline at the onset, with a deployment at that minute
- **WHEN** the cause is determined
- **THEN** the mode is `bad-deployment` rather than `monitoring-blind-spot`

#### Scenario: A read that could not be taken is not a blind spot
- **GIVEN** an incident whose metrics read failed rather than answering
- **WHEN** the incident's account is read
- **THEN** it says which read could not be taken, and no cause is named from
  the absence

### Requirement: The cause is sought from the minute the sight was lost onwards

Where the mode is a blind spot, the investigation SHALL read what changed from
the stated onset - the first minute no sample arrived for - through to the present,
rather than in a window ending at that minute.

Two facts about this mode make that the only window that can hold the cause.
The alert fires well after the onset, because an absence has to be held before
it can be reported, so a history read around the *firing* would miss the change
by however long the rule waits. And the change is at or after the onset rather
than before it, so a window ending at the onset - which is what every other
stated-onset incident is served - holds none of it either.

The stated onset SHALL be the only source of that minute for this mode. It is
not a fallback for a measurement that failed: a measurement is impossible here
by construction, since the rows that would carry a departure are the ones that
are missing.

#### Scenario: The change history reaches past the stated onset
- **GIVEN** an incident whose alert states the onset of an absence, having
  fired well after it
- **WHEN** the investigation reads what changed
- **THEN** the window it reads runs from the stated onset to the present rather
  than ending at that onset

#### Scenario: The deployment that ended the readings is what the mode is about
- **GIVEN** an incident named as `monitoring-blind-spot`
- **WHEN** its subject is read
- **THEN** it names the change that stopped the collecting
