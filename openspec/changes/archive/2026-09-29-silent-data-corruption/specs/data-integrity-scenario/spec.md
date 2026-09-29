## ADDED Requirements

### Requirement: A monthly total that stopped keeping up with its purchases

The Target Service SHALL stage a scenario in which a shopper's purchase is
recorded without being added to the running total of what they have spent this
month, so that the stored total falls further behind the purchases behind it with
every sale.

The drift SHALL be one-directional and SHALL accumulate. Nothing corrects it and
nothing notices it, which is what separates this from every scenario built so
far: the condition does not end when the cause is removed, because what is wrong
is what has already been written.

The account page SHALL go on rendering. The lifetime figure derives its own total
from the purchases and SHALL stay correct; the monthly figure reads the stored
total and SHALL be low. Two numbers on one page disagree, and neither of them
raises anything.

#### Scenario: The stored total falls behind the purchases
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** a shopper's purchases are added up and compared to their stored
  monthly total
- **THEN** the total is lower than the sum, by the purchases recorded since the
  scenario began

#### Scenario: The page renders a wrong number rather than an error
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** an affected shopper's account page is served
- **THEN** it answers successfully, and its monthly figure is lower than the
  purchases on the same page support

#### Scenario: The lifetime figure is unaffected
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the lifetime average is computed for an affected account
- **THEN** it is correct, because it derives its own total from the purchases

### Requirement: Nothing a monitoring stack watches moves

The Target Service SHALL leave every judged series at its baseline for the whole
of this scenario's window: `error_rate`, `p50_ms`, `p95_ms`, `p99_ms` and
`memory_used_bytes`. `cpu_used_cores`, `request_volume` and `cache_hit_ratio`
SHALL be unremarkable too.

This is the scenario rather than a property of it. A mode that moved any of the
five would be found the ordinary way, and the question it exists to ask - what
pages somebody when the only evidence is a value - would not arise.

#### Scenario: Every judged series is flat across the window
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** a window covering the incident is read
- **THEN** the error rate, all three quantiles and memory in use are at their
  baselines in every minute

#### Scenario: No onset can be measured from the metrics
- **GIVEN** a window retrieved for a staged silent-data-corruption scenario
- **WHEN** an onset is measured from it
- **THEN** none is found

#### Scenario: The logs say nothing about it
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the log lines for the window are read
- **THEN** none of them reports a failure, and none mentions a total or a
  summary

### Requirement: A check nobody outside the shop can reach is what finds it

The Target Service SHALL hold a data-integrity check which re-derives each
shopper's monthly total from their purchases and counts the accounts whose stored
total disagrees.

The check SHALL be the shop's alone. Argus SHALL NOT be able to trigger it, and
nothing in this design SHALL depend on its interval - what is stated is weekly,
and any interval a real shop chose must work the same way. The shop's database is
the check's and no part of it is ever Argus's.

The interval SHALL be a stated constant rather than a running scheduler. Nothing
in this service runs between requests: every answer is derived from live state
when something asks, which is what lets a scenario be staged and read
deterministically. A background job raising alerts on its own would race the
suite that stages the scenario, and would buy nothing - what the design rests on
is that Argus cannot reach the check, not that a timer somewhere is running.

#### Scenario: The check finds the accounts that disagree
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the integrity check runs
- **THEN** it reports the number of accounts whose stored total disagrees with
  their purchases, and the size of the largest gap

#### Scenario: A quiet shop reports nothing
- **GIVEN** no scenario staged
- **WHEN** the integrity check runs
- **THEN** it finds no account whose total disagrees, and raises no alert

### Requirement: The alert carries the finding, and the finding carries the onset

The Target Service SHALL fire an alert when the check finds enough accounts
disagreeing, in the same webhook shape every other alert takes, under a rule name
of its own.

Its summary SHALL state how many totals disagree, the largest gap, and **the
timestamp of the oldest affected purchase**. That last figure is the onset: when
the check ran says nothing about when the writing went wrong, and the oldest
disagreement is the only thing in the incident that dates it.

The finding SHALL NOT be offered through a retrieval tool. The alert is the whole
of this channel, and Argus reads it once.

#### Scenario: The alert says what was found and when it started
- **GIVEN** a staged silent-data-corruption scenario whose check has run
- **WHEN** the alert it fired is read
- **THEN** its name says totals do not reconcile, and its summary carries the
  count, the largest gap and the timestamp of the oldest affected purchase

#### Scenario: The onset predates the alert by far more than a window
- **GIVEN** a fired silent-data-corruption alert
- **WHEN** the oldest affected purchase is compared to the time the alert fired
- **THEN** it is older than the metrics source keeps

### Requirement: A flag caused it, and putting the flag back stops the bleeding without repairing anything

The Target Service SHALL stage this scenario behind a flag, so that the write
path that skips the total is live while the flag is on and gone when it is off.

Returning the flag SHALL stop new accounts drifting and SHALL NOT correct the
accounts that already have. Re-running the check afterwards SHALL still find
them, and SHALL find no affected purchase newer than the flip. That difference -
nothing new, everything old - is what recovery means for this mode, and it is not
something any series can show.

A restart SHALL change nothing. The fault is in what was written, and a fresh
process reads the same wrong totals.

#### Scenario: The flip stops the drift
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the flag is returned and further purchases are recorded
- **THEN** those purchases are added to their shoppers' totals

#### Scenario: The flip repairs nothing
- **GIVEN** a silent-data-corruption scenario whose flag has been returned
- **WHEN** the integrity check runs again
- **THEN** it still finds the accounts that had already drifted, and no affected
  purchase newer than the flip

#### Scenario: A restart changes nothing at all
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the service is restarted and the check is run
- **THEN** it reports what it reported before

### Requirement: The fault is planted in the code, and the shop's own suite stays green

The write path that skips the total SHALL be real code on the Target Service's
main branch, with no test over it in `tests/io_shop` - planted exactly as the
empty-month divisor is, and asserted as present in the harness suite beside it,
which the grader never runs.

`tests/io_shop` SHALL pass at the Target Service's head. The grader establishes
that the service was sound before it writes a patch in, and reads every failure
after that as belonging to the patch; a suite already red would fail that premise
for **every** fix in the corpus rather than for this one, on every push.

The red evidence a graded fix needs comes from the patch's own test files run
against the unfixed shop, which is how every existing fix is graded and which
works whether or not anything was failing beforehand.

There is nonetheless a defect in a file here for a patch to fix, which is what
separates this from the half-finished rollout - there neither revision was
faulty, and Code-Fix had nothing to find.

#### Scenario: The shop's own suite is green at its head
- **WHEN** `tests/io_shop` is run at the Target Service's head
- **THEN** it passes

#### Scenario: The harness suite asserts the fault is present
- **WHEN** the harness suite beside it is run
- **THEN** it finds the check reporting drifting accounts, the flip stopping the
  drift and repairing nothing, a restart changing nothing, and a quiet shop
  finding nothing

### Requirement: The two revisions are documentary, and the scenario says so

The write path before and after the fault SHALL both be real commits, pushed, with
their hashes constants in the scenario definition - and those constants SHALL
carry a comment saying that no channel serves them.

This scenario stages no deployment. The platform's revision history is empty for
a generated flag scenario, so nothing offers these hashes to Argus, and Code-Fix
works from the main branch by searching the code exactly as it does for a flag
toggle today. They are there so that a person and the fix grader can find the two
revisions, and a constant that looks like the cache port's without saying it is
read by nothing is a constant the next reader will wire something to.

No deployment SHALL be staged at the onset. One would be the deploy-caused
sibling this scenario deliberately excludes, and it would make a rollback the
obvious action where no rollback is available.

#### Scenario: The diff shows a write path that stopped keeping two things in step
- **WHEN** what the later commit changed is read
- **THEN** it shows a purchase being recorded with no corresponding addition to
  the stored monthly total

#### Scenario: Nothing serves the revisions to Argus
- **GIVEN** a staged silent-data-corruption scenario
- **WHEN** the deploy history for the window is read
- **THEN** it is empty
