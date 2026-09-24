## ADDED Requirements

### Requirement: A recorded fix is graded by the Target Service's own tests

The system SHALL decide whether a recorded Code-Fix patch works by running the
Target Service's test suite against it, and SHALL reach that verdict without
calling a model. Code-Fix proposes statically and never learns whether its patch
works; this is where that is found out, against patches already captured in the
committed corpus.

#### Scenario: A patch that fixes the fault and proves it

- **WHEN** a recorded patch's test files alone are written to the Target Service
  and its suite is run, and then the whole patch is written and the suite run
  again
- **THEN** the first run SHALL fail and the second SHALL pass
- **AND** the patch SHALL be reported as holding up

#### Scenario: A patch whose test proves nothing

- **WHEN** a recorded patch's test files alone are written and the suite passes
- **THEN** the patch SHALL be reported as having brought a test that passes
  without the fix
- **AND** it SHALL NOT be reported as holding up, whatever the whole patch does

#### Scenario: The red run failed somewhere else

- **WHEN** the suite fails with the patch's test files alone, and no failing test
  belongs to those files
- **THEN** the patch SHALL NOT be reported as holding up
- **AND** the failure SHALL be reported as unrelated to the patch, so that a
  pre-existing failure or a test file that will not import is not read as proof

#### Scenario: The tests that failed are the tests that pass

- **WHEN** the whole patch is applied after a red run
- **THEN** every test that failed in the red run and belongs to the patch's test
  files SHALL pass
- **AND** a patch whose own failing tests still fail SHALL NOT be reported as
  holding up

#### Scenario: A patch that breaks the service

- **WHEN** the whole patch is written and the suite fails
- **THEN** the patch SHALL be reported as leaving the suite red
- **AND** it SHALL NOT be reported as holding up

#### Scenario: A walk that proposed no fix

- **WHEN** a corpus contains no `submit_fix` answer
- **THEN** that scenario SHALL be reported as having nothing to grade
- **AND** it SHALL NOT be counted as a failure

### Requirement: The grader is written by a human, not by the agent it grades

The grader SHALL live under `tests/eval/` and SHALL be subject to the same
prohibition as every other test here: Claude proposes it and a human applies it.
The patches it grades were produced by a prompt Claude wrote, so a grader Claude
also wrote would be the agent marking its own work.

#### Scenario: The grader needs changing

- **WHEN** the grader's behaviour has to change
- **THEN** the change SHALL be proposed for a human to apply
- **AND** it SHALL NOT be written directly by Claude, nor moved outside `tests/`
  to make that possible

### Requirement: Grading never spends money and never records a result

Grading SHALL make no model call, and SHALL write no results file. Its inputs -
the recordings and the Target Service - are both committed, so a verdict for any
commit is recovered by checking that commit out and grading again. A stored
result would duplicate what version control already holds and would go stale the
moment a corpus is re-recorded.

#### Scenario: A verdict is recovered rather than looked up

- **WHEN** the verdict for an earlier corpus is wanted
- **THEN** grading SHALL be run again against that commit
- **AND** no file recording earlier verdicts SHALL exist to consult

#### Scenario: Grading reports as a gate

- **WHEN** any graded patch does not hold up
- **THEN** the run SHALL print which patch and why, and SHALL exit non-zero

### Requirement: Grading refuses to run over uncommitted work

Grading SHALL refuse to start when the Target Service's working tree has
uncommitted changes, and SHALL restore that tree even when grading fails
part-way. It grades by writing the patch into the tree and putting it back with
version control, so somebody's unfinished work there would be put back to the
last commit along with it.

#### Scenario: The Target Service has uncommitted changes

- **WHEN** grading starts and the Target Service's tree is not clean
- **THEN** grading SHALL refuse to run, SHALL say why, and SHALL write nothing

#### Scenario: Grading fails part-way

- **WHEN** the suite cannot be run, or grading raises after writing a patch
- **THEN** the Target Service SHALL be restored to its last commit, added files
  included
- **AND** files version control is told to ignore SHALL be left untouched
