## ADDED Requirements

### Requirement: A patch is written to a branch and never to the base
The system SHALL create a branch from the base branch's head and SHALL write
every file of a patch to that branch, naming the branch on each write. It SHALL
NOT write to the base branch. The credential it writes under SHALL reach the
Target Service's repository and no other (§15.1).

#### Scenario: A fix gets a branch cut from what is deployed
- **WHEN** a patch is written
- **THEN** the branch is created at the base branch's current head, so the fix
  applies to the code actually running

#### Scenario: Every write names the branch
- **WHEN** each file of a patch is written
- **THEN** the branch is named explicitly, so no write can fall back to the
  repository's default branch

#### Scenario: An existing file is replaced and a new file is created
- **GIVEN** a patch changing one file and adding another
- **WHEN** it is written
- **THEN** the change names the version it replaces, and the addition names none

### Requirement: A draft pull request is the furthest this tier goes
The system SHALL open pull requests as drafts and SHALL NOT expose any function
that merges one. Merging is a deploy and sits on the irreversible side of §13,
so the enforcement SHALL be that the function does not exist.

#### Scenario: The proposal carries the agent's own words
- **WHEN** a pull request is opened
- **THEN** its title and body are the ones the agent supplied, unaltered, and
  the body says which incident it answers

#### Scenario: A repository that refused is not reported as opened
- **WHEN** the repository refuses, is unreachable, or answers with no pull
  request in it
- **THEN** the call fails, so nothing downstream records a proposal that does
  not exist

### Requirement: Every file a patch names is written
The system SHALL write every path a patch names, tests included, and SHALL NOT
withhold any path from it. What bounds a change is the branch it lands on and
the human merge that would put it into service (§13) - not this tier's opinion
of which files an agent may touch.

#### Scenario: A patch that brings a test is written whole
- **GIVEN** a patch naming a source file and the test that exposes the bug
- **WHEN** it is written
- **THEN** both land on the branch, because the test is the half that shows the
  fix works

#### Scenario: Nothing in the repository is unwritable
- **WHEN** the tier's configuration and code are examined
- **THEN** there is no path it refuses and no setting that names one
