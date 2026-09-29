## MODIFIED Requirements

### Requirement: A patch is whole files
The system SHALL submit each changed or added file in full rather than as a
diff, and SHALL bring a regression test with the fix where one can be written.
A malformed entry in a submission SHALL cost that entry alone.

A submitted file whose content is not the language its path names SHALL be put
back to the model for another attempt rather than written out. Parsing is the
only evidence available here - the agent proposes statically and never runs what
it writes - so whether the content is source at all is the one thing that can be
established before a branch exists. It also catches a file that ends mid-statement
inside an answer that was otherwise complete, which is the half of truncation a
cut-short response does not cover.

It is put back rather than dropped because the model has already decided what to
write: an elision is a wrapping failure, not a judgement failure, and the
submission that follows is usually the fix written out properly. A file that
never arrives as source SHALL end the run as one that never answered, so that no
branch carries a file nothing can read.

#### Scenario: A file with no readable content is dropped
- **GIVEN** a submission naming a path whose content is not text
- **WHEN** the submission is read
- **THEN** that entry is dropped and the remaining files are proposed

#### Scenario: A whole submission is not lost to one bad entry
- **GIVEN** a submission of four files, one of them malformed
- **WHEN** the submission is read
- **THEN** the three readable files are proposed

#### Scenario: Content that is not source is put back rather than written
- **GIVEN** a submission whose file names a Python path and whose content does
  not parse as Python - a pointer to a patch written into the explanation, or an
  answer that stopped mid-file
- **WHEN** the submission is read
- **THEN** the file named is put back to the model as not source, and the fix
  submitted in its place is the one proposed

#### Scenario: A file that is never source reaches no branch
- **GIVEN** a model that submits content which is not source until its budget
  runs out
- **WHEN** the reading ends
- **THEN** the run is reported as one that never answered, and no branch is
  written and no pull request opened
