# monitoring-configuration-drift-scenario Specification

## Purpose
The Target Service staging the blind spot's silence from a change that was meant:
a revision renaming every port to one convention, a scrape configuration in the
repository left selecting the old name, and nothing but a merged change to that
configuration ending the silence.
## Requirements
### Requirement: A deliberate rename the scrape configuration did not follow

The Target Service SHALL stage a scenario in which a revision renames every port
in the deployment to one convention - each named for the protocol it carries -
and the metrics port's new name is one the scrape configuration does not select.
The shop SHALL go on serving, logging and answering exactly as in
`monitoring-blind-spot`, and the metrics SHALL stop at the onset the same way.

What separates this scenario from `monitoring-blind-spot` SHALL be the diff and
nothing else: there one port is renamed alone; here every named port is renamed
to the same rule in the same commit. The alert, the window, the logs and the
onset SHALL be indistinguishable between the two, so that the pair measures one
variable.

#### Scenario: The revision renames every port to one rule
- **GIVEN** a staged monitoring-configuration-drift scenario
- **WHEN** the deployed revision's diff against its predecessor is read
- **THEN** more than one port name changes, and every new name follows the same
  convention

#### Scenario: The metrics stop as a blind spot's do
- **GIVEN** a staged monitoring-configuration-drift scenario
- **WHEN** the metrics are read across the onset
- **THEN** rows exist before the onset and none at or after it, while the logs
  answer normally across the same minutes

### Requirement: The scrape configuration is a file in the repository

The Target Service's repository SHALL carry the scrape configuration as a file
beside the deployment's values, selecting the metrics port by name. On `main` it
SHALL name the port as it was before the convention, so that `main` holds the
fault the fix rolls forward. No test in `tests/io_shop` SHALL cover the
agreement between the two files at head.

#### Scenario: Main holds the stale name
- **WHEN** the scrape configuration and the values file on `main` are read
- **THEN** the port name the scrape selects is not the metrics port's name

#### Scenario: The suite is green at head
- **WHEN** `tests/io_shop` is run on `main`
- **THEN** it passes

### Requirement: Only a changed scrape configuration ends the silence

Returning the revision SHALL restore the collecting, as it does in
`monitoring-blind-spot` - the scenario does not pretend the rollback fails. What
makes it the wrong answer is that it undoes the convention. A restart SHALL
change nothing. Proposing a fix SHALL change nothing either, because a proposal
is not merged; the minutes after the onset SHALL stay uncollected for as long as
the scenario runs without a rollback.

#### Scenario: A proposed fix leaves the shop unread
- **GIVEN** a staged scenario on which no rollback was taken
- **WHEN** a further minute is served after a fix is proposed
- **THEN** no bucket exists for that minute

#### Scenario: A reset restores collecting
- **GIVEN** a staged scenario
- **WHEN** the scenario is reset
- **THEN** the next minute served carries a bucket

