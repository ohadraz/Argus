# code-fix-agent Specification

## Purpose
TBD - created by archiving change 2026-09-15-code-fix-proposes-a-pull-request. Update Purpose after archive.
## Requirements
### Requirement: A fix is proposed, never applied
The system SHALL propose a code fix as a **draft** pull request and SHALL NOT
merge one. Neither MCP server SHALL expose a function that merges, and the
binding the Code-Fix agent holds SHALL contain none - the guarantee being the
absence of the capability rather than a check a later caller could skip (§13).
Draft SHALL NOT be a parameter any caller can vary.

#### Scenario: A proposal is opened as a draft
- **WHEN** a patch is proposed
- **THEN** the pull request is opened as a draft, from the branch carrying the
  fix onto the branch it fixes

#### Scenario: There is no way to merge
- **WHEN** the tools available to Code-Fix are enumerated
- **THEN** no tool merges a pull request, applies infrastructure, or otherwise
  puts the change into service

### Requirement: What comes back is a place a person can read
The system SHALL return the pull request's number and the address it can be read
at. A fix that could not be proposed SHALL be distinguishable from a fix that
was not warranted.

#### Scenario: A proposed fix carries its address
- **WHEN** a pull request is opened
- **THEN** what the walk records is the address a human can open, and the
  incident's account says where it is

#### Scenario: Nothing to fix is an answer
- **WHEN** the agent submits a patch with no files in it
- **THEN** no branch is written and no pull request is opened, and the incident
  records that no code-level fix was found

#### Scenario: A repository that refused is not reported as a proposal
- **WHEN** the repository cannot be reached or refuses the work
- **THEN** the incident records that the fix could not be proposed, which is
  distinct from no fix being found, and the walk continues to the postmortem

### Requirement: A patch is whole files
The system SHALL submit each changed or added file in full rather than as a
diff, and SHALL bring a regression test with the fix where one can be written.
A malformed entry in a submission SHALL cost that entry alone.

#### Scenario: A file with no readable content is dropped
- **GIVEN** a submission naming a path whose content is not text
- **WHEN** the submission is read
- **THEN** that entry is dropped and the remaining files are proposed

#### Scenario: A whole submission is not lost to one bad entry
- **GIVEN** a submission of four files, one of them malformed
- **WHEN** the submission is read
- **THEN** the three readable files are proposed

### Requirement: A fix brings the test that proves it
The system SHALL propose the test exposing the bug alongside the change that
fixes it, in the same pull request, and SHALL withhold no path from the patch -
a repository with a file the agent may not write is one where a fix cannot
carry its own evidence. Whether a patch is correct SHALL be answerable from
outside the repository, by running the proposed tests against the base branch
and against the fix.

#### Scenario: A proposed fix carries its own test
- **WHEN** a patch is submitted for a fault in the code
- **THEN** it includes the test that fails against the deployed branch and
  passes against the fix

#### Scenario: No path is withheld from a patch
- **WHEN** a patch names a file anywhere in the service's repository
- **THEN** it is written, tests included - what bounds the change is that it
  lands on a branch nobody runs and that merging is a person's act

### Requirement: The reading is bounded and the cause is given
The system SHALL tell the agent what the investigation concluded rather than
asking it to investigate again, and SHALL bound how long it may read. The bound
SHALL NOT be expressed to the model.

#### Scenario: The agent is told the cause
- **WHEN** Code-Fix is invoked
- **THEN** the hypothesis the walk reached is put to it, and the incident it is
  fixing is named so the branch can be named after it

#### Scenario: A model that never answers proposes nothing
- **WHEN** the agent reads without ever submitting within its turns
- **THEN** nothing is written and nothing is proposed

