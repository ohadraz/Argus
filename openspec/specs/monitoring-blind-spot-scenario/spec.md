# monitoring-blind-spot-scenario Specification

## Purpose
TBD - created by archiving change monitoring-blind-spot. Update Purpose after archive.
## Requirements
### Requirement: A shop that goes on serving after it stops being collected from

The Target Service SHALL stage a scenario in which its telemetry stops being
collected while the shop itself stays well, so that every request is served
correctly and no minute of it is reported.

Orders SHALL succeed, the account pages SHALL render the figures they render
with no scenario active, and no request SHALL fail or slow down for the whole
of the scenario's window. What is wrong SHALL be on the observer's side of the
wire and nowhere else.

This is the scenario rather than a property of it. Every mode built so far
stages something the shop does badly and asks Argus what it means; this one
stages a shop doing nothing wrong at all, and asks Argus not to conclude from
the absence of evidence that there is nothing to find.

#### Scenario: The shop serves correctly throughout
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** an account page is served
- **THEN** it answers successfully, with the figures it carries when no
  scenario is active

#### Scenario: Nothing the shop does is affected
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** a purchase is recorded and the shopper's totals are read back
- **THEN** both are what they are with no scenario active

### Requirement: The window stops at the onset rather than being empty or flat

`GET /metrics` SHALL carry a row for every minute before the revision landed
and **no row for any minute at or after it**.

The onset is the minute the revision landed, which is the first minute carrying
no row - not the last minute that carries one. A minute the shop spent any part
of not being collected from has no full reading of itself, so the minute
containing the change is withheld entire, and the onset is that minute rather
than the one to its left.

That boundary is load-bearing rather than tidy, and one consumer decides it.
Whether any reading covers the incident's own minutes is asked as "is there a
bucket at or after the onset", and the answer is what tells the change channel
whether to bound its window at the onset or reach past it. An onset placed at
the last *heard* minute carries a bucket of its own, answers yes, and leaves
the change that explains the incident outside every window the model can ask
for. An onset that precedes its own cause is the one shape this scenario must
not have.

The minutes at or after the onset SHALL be genuinely absent. They SHALL NOT be
present with readings of zero, and they SHALL NOT be present with readings at
baseline. A bucket of zeros describes a shop serving nothing, a bucket at
baseline is the flat window FM-26 stages, and either one would be a different
mode wearing this one's name.

The quiet stretch before the onset SHALL be present and SHALL be ordinary. It
is what every other scenario's onset is measured against, and here it is what
makes the stopping legible at all: a window with no rows anywhere in it would
describe a shop that was never instrumented, which is not a blind spot and not
something an absence rule fires for.

That same stretch is the scenario's trap, and it is deliberate. Rows that
simply stop read as a window that is merely short, which is a conclusion
nothing in the evidence contradicts and which is wrong. The mode is harder than
an empty window rather than easier, because an empty window is unmistakably
nothing and a plausible one provokes no question.

#### Scenario: Rows are present before the onset
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** a window covering the incident is read
- **THEN** every minute before the onset carries a bucket, and those buckets
  are unremarkable

#### Scenario: No row exists at or after the onset
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** a window covering the incident is read
- **THEN** no bucket has a minute at or after the onset

#### Scenario: The missing minutes are absent rather than zeroed
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the buckets for the minutes at or after the onset are looked for
- **THEN** there are none, rather than buckets reporting zero or reporting
  baseline

#### Scenario: No onset can be measured from the metrics
- **GIVEN** a window retrieved for a staged monitoring-blind-spot scenario
- **WHEN** an onset is measured from it
- **THEN** none is found, because the minutes that would carry a departure are
  the ones that are missing

### Requirement: The logs go on answering across the minutes the metrics do not

`GET /logs` SHALL serve lines for the whole of the scenario's span, the dark
minutes at and after the onset included, and those lines SHALL report a shop
serving normally.

This is the corroboration the mode turns on, and it is the only channel that
carries it. The metrics say nothing because they are missing; the logs say the
shop is well because it is. A scenario whose logs also stopped would stage an
observability outage - two channels down at once, with nothing left to say
whether the shop behind them was alive - and Argus would be right to escalate
it rather than diagnose it.

The lines SHALL NOT mention telemetry, collection, the deployment, or their
stopping. What makes the dark minutes legible is that they are ordinary, and a
log line announcing the cause would put the answer in the one channel that
still answers.

They SHALL be indistinguishable from the lines any other scenario's shop
serves. A shop that went quieter, or noisier, or started saying something new
at the onset would make the dark minutes conspicuous in the one channel whose
ordinariness is the evidence.

#### Scenario: Logs answer for the minutes the metrics are missing
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the log lines for a window covering the incident are read
- **THEN** lines exist for every minute at and after the onset, each of which
  carries no bucket

#### Scenario: The logs describe a shop that is well
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the log lines for the minutes at and after the onset are read
- **THEN** none of them reports a failure, and none mentions telemetry,
  collection or a deployment

### Requirement: An absence held long enough to be an absence, and long enough to be seen

The Target Service SHALL fire an alert whose subject is that a series which was
reporting has stopped, in the same webhook shape every other alert takes, under
a rule name of its own. The rule SHALL be an absence rather than a threshold:
no series crosses one here, because no series exists to cross one.

The absence SHALL be held long enough that it cannot be a scrape that was
missed. One absent minute is a gap every real monitoring stack sees and none
pages for, and a rule that fired on one would fire most days.

The alert SHALL fire materially later than the last sample it is about, and
that figure is load-bearing twice over. It is what makes the absence a
condition rather than a gap - and it is the whole of what makes this incident
**detectable by the model at all.**

Nothing put in front of the Investigator states what time it is now. It is
given the minute the alert fired, the stated onset, and the rows; the rows
themselves are the only account of the span, so a window that stops cannot be
seen to stop *early*. The distance between the last row and the alert's firing
is therefore the whole of the evidence that anything is missing, and it is
stated to the model rather than left to be worked out - a fact Argus holds both
halves of is not one to hand over half of.

What this scenario owes that requirement is the distance itself. An alert
firing in the same minute as its last sample leaves nothing to state and
nothing to notice, and the mode would then be undiagnosable by construction
rather than merely difficult.

#### Scenario: The alert says a series stopped reporting
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the alert it fired is read
- **THEN** its name says a series is no longer reporting, and its summary says
  the shop has stopped being collected from rather than that anything it serves
  is wrong

#### Scenario: A single missing minute pages nobody
- **GIVEN** one absent minute and the shop being collected from again
- **WHEN** the absence rule is evaluated
- **THEN** it does not fire

#### Scenario: The alert fires well after the last sample
- **GIVEN** a fired monitoring-blind-spot alert
- **WHEN** the minute it fired is compared to the last minute the metrics carry
- **THEN** the alert is later by more than the absence the rule requires

### Requirement: The alert carries the first silent minute as the onset

The alert SHALL carry the first minute it received no sample for, in the same
annotation that already carries an onset a consumer has to do arithmetic with.

What an absence rule knows is exactly that minute, and that minute is exactly
the onset: the sight stopped when the samples stopped. So the machinery FM-26
built for an alert that states its own onset answers this mode unchanged, and
nothing new is needed to accept it.

The stated onset SHALL be the only source of the onset for this mode, and not a
fallback. A measured onset is impossible here by construction rather than by
accident - the minutes that would carry a departure are the missing ones - so a
later change that prefers measurement wherever it is available SHALL NOT leave
this mode undatable.

#### Scenario: The onset is the first minute that reported nothing
- **GIVEN** a staged monitoring-blind-spot scenario whose alert has fired
- **WHEN** the onset the alert states is compared to the metrics
- **THEN** it is the minute after the last bucket the window carries, and no
  bucket exists at it

#### Scenario: The cause is looked for from the stated onset onwards
- **GIVEN** an incident whose alert states the onset of an absence
- **WHEN** the investigation reads what changed
- **THEN** it reads the change histories from the stated onset to the present,
  rather than in a window ending at that onset or around the minute the alert
  fired

### Requirement: A deployment stopped the collecting, and returning it restores the sight

The Target Service SHALL stage this scenario behind a deployment: a revision
that renames the port the shop's metrics are served on, so that the scrape no
longer finds them. The revision SHALL change nothing else, and its commit
message SHALL read as housekeeping - nobody ships a change meaning to go blind,
and a revision announcing itself would put the answer in the change channel.

The revision SHALL be reachable as a real commit, with the revision before it
deployed and recorded, so that a rollback has somewhere to go and a reader has
a diff to read.

Rolling the deployment back SHALL restore the collecting, and the minutes
served after it SHALL carry buckets again. Those buckets SHALL report the same
well shop the logs have been reporting throughout - there is no level to come
back down to, because nothing ever went up.

The minutes lost while the revision was deployed SHALL stay lost. They were
never collected and nothing retains them, so returning the deployment restores
the sight without restoring the record. That is what recovery means here, and
it is the one thing this mode has in common with silent data corruption: the
condition ends and something of what it cost does not come back.

#### Scenario: Rolling the deployment back restores the collecting
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the deployment is rolled back and a further minute is served
- **THEN** a bucket exists for that minute

#### Scenario: The restored minutes report a healthy shop
- **GIVEN** a monitoring-blind-spot scenario whose deployment has been returned
- **WHEN** the buckets served after the return are read
- **THEN** every judged series is at its baseline in each of them

#### Scenario: The minutes it was blind for do not come back
- **GIVEN** a monitoring-blind-spot scenario whose deployment has been returned
- **WHEN** a window covering the incident is read
- **THEN** the minutes between the onset and the return still carry no bucket

### Requirement: A restart is refuted, and the scenario makes that legible

Restarting the shop SHALL change nothing. The revision is still deployed
afterwards, the minutes are still missing, and the window a verification reads
SHALL carry nothing at or after the action's minute.

This is what an agent reaching for the process learns, and it is worth staging
rather than merely permitting. A restart is the cheapest action Argus has and
the one a thin diagnosis reaches for, and a mode where it silently appeared to
work would teach the wrong lesson. Here it is refutable on the evidence, and
the walk still has the rollback ahead of it.

#### Scenario: A restart leaves the shop blind
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the service is restarted and a further minute is served
- **THEN** no bucket exists for that minute

#### Scenario: A restart leaves a candidate still to try
- **GIVEN** a staged monitoring-blind-spot scenario whose restart has been tried
- **WHEN** the deployment is then rolled back and a further minute is served
- **THEN** a bucket exists for that minute

### Requirement: Nothing offers the cause through a channel of its own

The scenario SHALL be investigable from the channels that already exist. The
absence SHALL arrive in the metrics read Argus already takes, the corroboration
in the logs channel it already has, and the cause in the deploy history it
already reads.

No retrieval channel, tool or endpoint SHALL be added for this mode. Every
existing recording stays valid for exactly that reason, and a sixth channel
would invalidate all of them to carry a fact three channels already carry
between them.

#### Scenario: The deployment is in the history Argus already reads
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the deploy history from the stated onset onwards is read
- **THEN** it holds the revision that stopped the collecting

#### Scenario: No flag is staged at the onset
- **GIVEN** a staged monitoring-blind-spot scenario
- **WHEN** the flag history for the window is read
- **THEN** it holds no change, so no flag revert is ranked for an incident no
  flag caused

