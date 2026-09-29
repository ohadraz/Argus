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

### Requirement: Which retrieval channel the agent gets is configured
The system SHALL assemble the agent's retrieval tools from configuration -
substring search, retrieval by meaning, or both - and SHALL retain both
implementations whichever is configured. Neither SHALL replace the other, so
that which one localizes a fault better on a given repository stays a question
the benchmark can put rather than one the code has already answered.

#### Scenario: The agent is offered what it was configured to have
- **GIVEN** retrieval by meaning is the configured channel
- **WHEN** the agent's tools are assembled
- **THEN** the meaning channel is among them, and the loop is otherwise unchanged

#### Scenario: Both channels can be offered at once
- **GIVEN** both channels are configured
- **WHEN** the agent's tools are assembled
- **THEN** it may search by substring and by meaning within the same attempt

#### Scenario: Neither implementation is removed
- **WHEN** the retrieval implementations available to the agent are enumerated
- **THEN** both substring search and retrieval by meaning are present, whatever
  is configured

### Requirement: The agent is told when what it searched is behind
The system SHALL state in the agent's opening message, as a fact rather than a
caveat, when the index it will search describes an earlier commit than the
deployed branch, naming the commit indexed and the commit deployed. The agent
SHALL NOT be left to infer this from what it reads.

A limitation the model cannot detect from the inside is stated to it, on the same
rule the investigation loop follows for a bound it cannot see: a model reading
passages from an earlier commit reports the same confidence as one reading
current code, because it cannot miss what it was never shown.

#### Scenario: A behind index is stated up front
- **GIVEN** the index describes an earlier commit than the deployed branch
- **WHEN** the agent is opened
- **THEN** the message states that the code it can retrieve may not be the code
  deployed, and names both commits

#### Scenario: A current index is not remarked on
- **GIVEN** the index describes the deployed commit
- **WHEN** the agent is opened
- **THEN** the message says nothing about staleness

### Requirement: A retrieval channel that failed is not a failed attempt
The system SHALL answer a failed retrieval call as a tool result the agent reads,
as it does for every other tool, and SHALL NOT end the attempt on one. An agent
offered both channels SHALL be able to fall back to the other.

#### Scenario: An unreachable index costs one turn
- **GIVEN** the vector store cannot be reached
- **WHEN** the agent retrieves by meaning
- **THEN** it is told the call failed, keeps the turns it has left, and may
  search by substring instead

### Requirement: A fix may carry the repair of what the fault already wrote

The system SHALL allow a proposed fix to contain, beside the change that stops
the fault, a second file that repairs the data the fault has already written.

Some faults leave a residue. A write path that stopped keeping two values in step
is fixed by a patch, and every value it already wrote stays wrong afterwards -
so a pull request holding only the patch is a pull request that closes an
incident while leaving the damage in place. Both belong in one pull request,
because they are one change: a reviewer approving the fix is approving what has
to happen to the rows behind it.

#### Scenario: The repair is proposed beside the fix
- **GIVEN** a cause whose fault has already written wrong values
- **WHEN** a fix is proposed for it
- **THEN** one pull request carries both the change that stops the fault and a
  script that repairs what it wrote

#### Scenario: An ordinary fix is unchanged
- **GIVEN** a cause whose fault left nothing behind
- **WHEN** a fix is proposed for it
- **THEN** the pull request carries the change alone

### Requirement: A repair is proposed and never run

The system SHALL NOT execute a repair it proposes, and SHALL hold no capability
that could. A repair rewrites stored data and cannot be undone by putting a value
back, which places it outside what Argus may do unasked by the same rule that
keeps it from merging its own pull requests (§13).

#### Scenario: Nothing in the binding can run a repair
- **WHEN** the functions available to the Code-Fix agent are enumerated
- **THEN** none of them executes a script against the target's data

#### Scenario: The pull request says the repair is owed
- **GIVEN** a pull request carrying a repair script
- **WHEN** its body is read
- **THEN** it says the repair has not been run and that a person must run it
