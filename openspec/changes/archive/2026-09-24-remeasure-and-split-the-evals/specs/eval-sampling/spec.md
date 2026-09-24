## ADDED Requirements

### Requirement: A paid eval run takes a batch, not a population

An eval that calls the real model SHALL take 10 samples of each case it runs, and
SHALL allow a run to cover a subset of its cases. Samples are independent, so a
population is reached by running more batches; requiring every case on every run
is a cost paid in one afternoon for an answer that does not need it. Ten per case
is a floor rather than a target - below it a batch distinguishes nothing short of
total failure.

#### Scenario: An eval run is asked for

- **WHEN** a paid eval session runs
- **THEN** it SHALL take 10 samples of each case it runs
- **AND** it SHALL NOT require any particular total to have been reached

#### Scenario: One case is asked for

- **WHEN** a run is asked to cover a single case
- **THEN** it SHALL take that case's 10 samples and no others
- **AND** those samples SHALL pool with earlier samples of the same case

### Requirement: An eval measures under the budget it declares

An eval SHALL restate the budget its samples were taken under, and that
restatement SHALL match the configured default it names. A score taken under a
bound the deployment does not use is a measurement of something nobody runs.

#### Scenario: The configured budget changes

- **WHEN** a bound the eval restates is changed in configuration
- **THEN** the eval's restatement SHALL be changed with it
- **AND** the thresholds resting on the old bound SHALL be treated as
  invalidated

#### Scenario: A regression is looked for

- **WHEN** the pass rate of a single batch is compared against the threshold
- **THEN** the comparison SHALL be treated as detecting a regression, not as
  re-deriving a threshold

### Requirement: Paid samples are recorded and pooled

Every sample a paid eval takes SHALL be appended to a committed results file,
one row per sample, carrying at least the date, the commit, the case and the
outcome. The pass rate SHALL be computed over every recorded sample taken since
the last change to the prompt under test.

#### Scenario: A batch finishes

- **WHEN** a paid eval run completes
- **THEN** each sample SHALL be appended to the results file
- **AND** no earlier row SHALL be rewritten or removed

#### Scenario: Batches are pooled

- **WHEN** the pass rate is computed
- **THEN** it SHALL be computed over all recorded samples since the last prompt
  change, not over the most recent batch alone

#### Scenario: The prompt under test changes

- **WHEN** the standing brief, a tool description or a budget changes
- **THEN** samples taken before that change SHALL NOT be pooled with samples
  taken after it

### Requirement: A threshold is re-derived only from a deep enough pool

A threshold SHALL be re-derived only once the pooled samples since the last
prompt change are numerous enough for the derived figure to mean something, and
the derivation SHALL record how many samples it rested on. A threshold fitted to
a single batch states a precision the batch does not have.

#### Scenario: A threshold is proposed from a shallow pool

- **WHEN** a threshold would be derived from fewer samples than the pool depth
  the eval declares
- **THEN** the threshold SHALL NOT be changed
- **AND** the shortfall SHALL be reported

#### Scenario: A threshold is derived

- **WHEN** a threshold is re-derived
- **THEN** the number of samples it rested on SHALL be recorded alongside it

### Requirement: What can be recomputed is not recorded

A result SHALL be written down only when it cannot be recomputed from what is
already committed. Deterministic outcomes over committed inputs SHALL be
recomputed on demand instead of stored.

#### Scenario: A deterministic grader finishes

- **WHEN** a grader that makes no model call produces a verdict
- **THEN** no results file SHALL be written

#### Scenario: A measurement cannot be recomputed

- **WHEN** an outcome depends on the model's answer on the day, or on wall-clock
  time
- **THEN** it SHALL be recorded, because re-running it costs money and may not
  reproduce
