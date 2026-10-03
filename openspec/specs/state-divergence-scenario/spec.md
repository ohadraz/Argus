# state-divergence-scenario Specification

## Purpose
Staging the failure mode where two stores hold the same thing and disagree
about it, and the one that is wrong is the copy: replication to the summary
cache's standby broke, nothing reads a standby so nothing noticed, and the
standby was promoted when the primary died. The shop then serves spend figures
the purchase ledger has moved past - quickly, successfully, and with every
series a monitoring stack watches sitting exactly where it was. What pages
somebody is the shop's own data-integrity check, which carries the count that
disagree, the widest gap, and the keys of the entries it found stale. Two dates
arrive with it and only the later one is the onset.
## Requirements

### Requirement: The scenario stages a promoted stale replica, not a cache fault

The Target Service SHALL offer a generated scenario in which replication to the
summary cache's standby broke, went unnoticed because nothing reads a standby, and
was then promoted when the primary died - so the cache answers every lookup,
answers it quickly, and answers some of them with a figure the purchase ledger has
moved past.

The ledger SHALL be correct throughout. What diverged is a derived copy, and that is
the whole of the fault - which is what separates this from silent data corruption,
where the authoritative copy is the wrong one and no action reaches it.

The promotion SHALL be the onset, and it SHALL cross no threshold in any series. The
shop goes on trading: orders succeed, nothing throws, nothing waits, the cache
answers at the ratio it always did, the heap is flat and the deployment is the size
it was asked to be.

#### Scenario: The cache answers, and answers stale
- **GIVEN** the scenario is staged and the promotion has happened
- **WHEN** an account page reads the cache for an affected shopper
- **THEN** it is answered within the cache's usual time, with the figure that
  shopper's entry held when replication broke

#### Scenario: The ledger is untouched
- **GIVEN** the scenario is staged
- **WHEN** a shopper's purchases are read
- **THEN** every purchase is there, and their sum is the figure the cache should be
  holding

#### Scenario: No change channel carries anything
- **GIVEN** the scenario is staged
- **WHEN** the flag history, the deploy history and the rollout status are read
  across the window
- **THEN** no flag moved, no revision was deployed, and no rolling update is in
  flight

### Requirement: Entries are seeded and never rewritten

The Target Service SHALL seed each active account's entry with the figure it held at
the minute replication broke, and SHALL NOT rewrite, invalidate or expire an entry
afterwards.

The shop has no cache write path: the seam a cache is reached through is read-only,
and a purchase is not a recorded event - the accounts the check examines derive their
purchases from a fixed grid as of the instant asked. There is nothing to hang an
invalidation on, and the scenario SHALL NOT be given one.

#### Scenario: An entry holds what it held at the lag's start
- **GIVEN** an active account whose entry was seeded
- **WHEN** that entry is read at any later minute
- **THEN** it holds the figure and the item count correct as of the minute
  replication broke

#### Scenario: Nothing updates an entry
- **GIVEN** an affected account that buys again
- **WHEN** its entry is read
- **THEN** it is unchanged

### Requirement: The divergence grows while the incident is open

The Target Service SHALL stage a stale set that grows: an account diverges as soon as
it buys after the lag began, so the count climbs with time until every account the
check examines is stale.

This is what a promoted stale replica does, and the scenario SHALL describe it rather
than engineer around it. What closes the set is the lasting fix in the cache's own
operation - a time-to-live, or refusing to promote a replica that is behind - and
nothing in the shop or in the mitigation does.

#### Scenario: The count climbs with the lag
- **GIVEN** the scenario is staged
- **WHEN** the check is run at two minutes further apart than the shop's order
  cadence
- **THEN** the later run finds more accounts disagreeing than the earlier one

### Requirement: The stale share is derived from the shop's own order grid

The Target Service SHALL derive the stale count from the constant that fixes how
often the shop takes an order, and SHALL NOT hardcode it.

Both integrity scenarios then stand on one grid, and the count is checkable in one
division: the lag in minutes over the shop's order cadence, capped at the accounts
the check examines. A regenerated grid therefore changes the count and fails a test,
where a hardcoded figure would quietly disagree with the purchases behind it.

#### Scenario: The count follows from the cadence
- **GIVEN** a staged lag
- **WHEN** the count of disagreeing accounts is set against the lag and the order
  cadence
- **THEN** it is the lag divided by the cadence, capped at the accounts examined

### Requirement: An affected account page contradicts itself twice

The Target Service SHALL render, for an affected shopper, a monthly total and a count
of the purchases behind it drawn from the cache, beside a list of purchases drawn
from the ledger - so that two figures on one page disagree with what is printed under
them.

Both halves SHALL render successfully. Nothing is caught, nothing falls back, and the
page returns 200 - which is what separates this from the in-flight compatibility
break, where the two sides disagree about an entry's *shape* and the page fails.

Two diverging fields rather than one, because a cache entry carries the figure and
the purchases it was worked out over. It also separates this from silent data
corruption in the evidence rather than only in the prose: there the amount is wrong
and the item count is not.

#### Scenario: The page shows a total and a count its own list contradicts
- **GIVEN** an affected shopper whose purchases come to a figure the cache does not
  hold
- **WHEN** their account page is rendered
- **THEN** it returns 200, shows the cache's figure and item count, and lists
  purchases that come to a different figure over a different number of items

#### Scenario: An unaffected shopper's page agrees with itself
- **GIVEN** an account that has not bought since replication broke
- **WHEN** their account page is rendered
- **THEN** the total, the item count and the purchases beside them agree

### Requirement: The generic signals stay exactly where they were

The Target Service SHALL leave every series a monitoring stack watches unmoved across
the window: the error rate, the median, the 95th and 99th percentiles, the heap, CPU
against its limit, and the replica count.

This is the property the scenario exists for. A stale cache is invisible in generic
telemetry, and no series that Argus already reads - and no series invented for Argus
to read - carries it.

#### Scenario: Every judged series is flat
- **GIVEN** the scenario is staged
- **WHEN** the metrics window is read from before the promotion to now
- **THEN** every minute carries a reading, and no series departs its baseline at any
  minute

### Requirement: The shop's own data check is what pages somebody

The Target Service SHALL fire an alert from its own data-integrity job, which
compares what the cache holds against the purchases behind it, and SHALL NOT publish
a series, an endpoint or a metric existing for Argus's benefit.

The alert SHALL carry how many cached figures disagree, out of how many were checked,
the widest gap in cents, how many purchases the most incomplete figure is missing,
and the cache keys of the entries found stale. The two figures are separate facts
about possibly different entries - one shopper may have bought a single expensive
thing and another three cheap ones - so they SHALL NOT be reported as one entry's
gap over one entry's missing purchases, which would describe an entry that need
not exist. The keys are carried because the job addressed the cache to
compare it and therefore already holds them, and because the shop's key format is the
shop's own - a consumer that derived a key would be a consumer holding this shop's
internals.

The alert SHALL state that the key list is a snapshot at the minute the check ran,
because the set goes on growing after it.

#### Scenario: The check fires and names what it found
- **GIVEN** cached figures that disagree with the purchases behind them
- **WHEN** the data-integrity job runs
- **THEN** it fires an alert carrying the count that disagree, the count checked, the
  widest gap, how many purchases the most incomplete figure is missing, and the
  keys of the stale entries

#### Scenario: The key list is as long as the count
- **GIVEN** an alert reporting a number of disagreeing figures
- **WHEN** the keys it carries are counted
- **THEN** there are exactly that many, so a truncated list cannot read as a smaller
  incident

#### Scenario: The snapshot is declared
- **GIVEN** an alert from this check
- **WHEN** it is read
- **THEN** it says the keys are those found stale at the minute the check ran

#### Scenario: Nothing Argus-shaped is exposed
- **GIVEN** the scenario is staged
- **WHEN** the shop's metrics endpoint and its HTTP surface are read
- **THEN** no series and no route exists whose only consumer could be an
  incident-response agent

### Requirement: The incident carries two dates, and the onset is the promotion

The Target Service SHALL state the promotion's minute as the onset, and SHALL carry
the oldest purchase no stale figure accounts for as a separate, earlier fact: when
replication broke.

The two are hours apart and they mean different things. The promotion is when
customers began seeing wrong figures; the older date is when the copy started going
wrong while nobody could see it. A reader who takes the older one for the onset dates
the incident from before anybody could have seen it, and then looks for a cause in
minutes where nothing was wrong.

The Target Service SHALL log the reconnection to a new primary at the promotion
minute, so the onset has corroboration in a channel that exists for the shop's own
reasons.

#### Scenario: The onset is the promotion
- **GIVEN** a lag that began hours before the promotion
- **WHEN** the alert is read
- **THEN** the onset it states is the promotion's minute

#### Scenario: The lag's start is carried separately
- **GIVEN** the same alert
- **WHEN** it is read
- **THEN** the oldest purchase no stale figure accounts for is carried as the
  replication break, distinct from the onset

#### Scenario: The log corroborates the onset
- **GIVEN** the scenario is staged
- **WHEN** the shop's log is read across the window
- **THEN** the promotion minute carries a line recording the reconnection to a new
  primary

### Requirement: Discarding the stale entries ends the incident, and the failover is untouched

The Target Service SHALL serve a correct figure for any shopper whose entry has been
discarded, by working it out from the ledger on the next read.

The promoted standby SHALL remain the cache being served, on the endpoint the
deployment configured, and nothing about the replication that let it fall behind SHALL
change - so the shop is correct and the condition that made it wrong is still there.

#### Scenario: A discarded entry renders correctly
- **GIVEN** an affected shopper whose cache entry has been discarded
- **WHEN** their account page is rendered
- **THEN** the total and the item count are worked out from the ledger and agree with
  the purchases beside them

#### Scenario: Discarding changes nothing about the cache itself
- **GIVEN** every stale entry the check named has been discarded
- **WHEN** the cache is asked what it is
- **THEN** it is the promoted standby still, serving on the endpoint the deployment
  configured

### Requirement: The cache is a real Redis, reached by this scenario alone

The Target Service SHALL keep this scenario's cache entries in a real Redis reached
over the real protocol, so that the action taken against them is the action a
responder would take.

Every other scenario's cache behaviour SHALL remain computed, and the real client
SHALL be reached only while this scenario is live. A shop dialling the address its
deployment configured would otherwise be *genuinely* refused where that address is
wrong, which turns the misconfiguration scenario from arithmetic into a real outage
and invalidates its recordings.

The entropy the cache's own staging draws SHALL be drawn unconditionally and in the
order it already is, so that a request which skips the cache cannot shift the
sequence for the requests after it - which is what makes every other scenario
identical by construction rather than by comparison.

#### Scenario: Entries exist as keys in Redis
- **GIVEN** the scenario is staged
- **WHEN** the keys the alert named are read from Redis
- **THEN** each holds the stale entry the account page renders

#### Scenario: Another scenario reaches no real cache
- **GIVEN** any scenario other than this one
- **WHEN** it is staged and its window is generated
- **THEN** nothing dials Redis, and its telemetry is what it was before Redis existed
  in the stack

#### Scenario: The draws are unchanged
- **GIVEN** the cache's staging for any scenario
- **WHEN** its entropy draws are counted and ordered
- **THEN** both are taken unconditionally, in the order they were taken before
