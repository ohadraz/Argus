# deployed-data-integrity-scenario

## Purpose
A second silent-data-corruption scenario in the Target Service, staged so that
the drift is caused by a deployment rather than a flag. A shopper's purchase is
recorded without being added to their running monthly total - the same drift,
accounts, page, flat window and integrity-check alert as the flag scenario - and
the two differ in their change history and nowhere else: the deploy history holds
one deployment of the faulty revision at the onset, and the flag history holds
nothing. That isolation is the point. It tests whether Argus's action follows the
change the record names rather than the mode, so that a walk which reads a flat
window and reaches for a flag revert is caught having learned the scenario
instead of the mode. The faulty revision is a pair of real commits on a branch
that is never merged, so the Target Service's main branch, its own tests and the
fix corpus stay frozen, and returning the deployment stops the drift while
repairing none of it.

## Requirements

### Requirement: The same drift, caused by a deployment

The Target Service SHALL stage a second scenario under silent data corruption in
which a shopper's purchase is recorded without being added to their running
monthly total - the same drift, the same accounts and the same page as the flag
scenario - and in which what turned that write path on is a deployment rather
than a flag.

Everything a monitor or the integrity check sees SHALL be identical to the flag
scenario's: every judged series at its baseline throughout, logs reporting no
failure, and the check's alert carrying the count, the widest gap and the oldest
affected purchase as the onset. The two scenarios differ in their change history
and nowhere else, because what this one exists to test is whether the action
follows the change rather than the mode.

#### Scenario: The check finds the same drift
- **GIVEN** a staged deploy-caused corruption scenario
- **WHEN** the integrity check runs
- **THEN** it reports accounts whose stored monthly total is below their
  purchases, and an oldest affected purchase older than the metrics source keeps

#### Scenario: Every judged series is flat
- **GIVEN** a staged deploy-caused corruption scenario
- **WHEN** a window covering the incident is read
- **THEN** no onset can be measured from it

### Requirement: The deploy history names a revision and the flag history names nothing

The Target Service SHALL record a deployment of the faulty revision at the stated
onset, and SHALL record no flag change anywhere near it.

A flag change at that minute would make this the flag scenario with a deployment
beside it - the competing-changes shape, which is a different question. The
history holding exactly one change, of the other kind, is what makes a flag
revert here an answer with nothing behind it.

#### Scenario: The deploy history holds the revision at the onset
- **GIVEN** a staged deploy-caused corruption scenario
- **WHEN** the deploy history around the stated onset is read
- **THEN** it holds one deployment, of the revision that dropped the monthly
  addition, at that onset

#### Scenario: The flag history is empty
- **GIVEN** a staged deploy-caused corruption scenario
- **WHEN** the flag history around the stated onset is read
- **THEN** it holds no change

### Requirement: The revision is a real commit on a branch of its own

The deployed revision and the one before it SHALL be real commits, pushed, whose
diff shows a purchase recorded with no addition to the stored monthly total and
no flag guarding it. They SHALL sit on a branch that is never merged, so the
Target Service's main branch, `tests/io_shop` and the fix corpus are untouched.

A deployed revision only has to be a commit the change channel can compare
against, not one the history leads to - which is how the control-plane scenario's
revision is staged, and for the same reason.

#### Scenario: The diff shows the addition removed unconditionally
- **WHEN** what the deployed revision changed is read
- **THEN** it shows the monthly addition removed, and no flag consulted

#### Scenario: Main is untouched
- **WHEN** `tests/io_shop` is run at the Target Service's head
- **THEN** it passes, as it did before this scenario existed

### Requirement: Returning the deployment stops the drift and repairs nothing

The Target Service SHALL stop the drift when the deployment is returned to the
revision before it, and SHALL leave every account that already drifted as it was.
A restart SHALL change nothing.

This is the flag scenario's recovery said of the other change, and it is what
makes the rollback an honest recommendation: it is the action that stops the
damage growing, even though nothing in the window could show it doing so.

#### Scenario: The rollback stops the drift
- **GIVEN** a deploy-caused corruption scenario whose deployment has been returned
- **WHEN** further purchases are recorded
- **THEN** they are added to their shoppers' monthly totals

#### Scenario: The rollback repairs nothing
- **GIVEN** a deploy-caused corruption scenario whose deployment has been returned
- **WHEN** the integrity check runs again
- **THEN** it still finds the accounts that had drifted, and no affected purchase
  newer than the rollback
