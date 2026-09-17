# semantic-code-retrieval Specification

## Purpose
TBD - created by archiving change 2026-09-17-rag-retrieval-for-code-fix. Update Purpose after archive.
## Requirements
### Requirement: The source can be retrieved by meaning
The system SHALL answer a description of what some code does with the passages
of the service's source that are nearest it in meaning, ranked, and bounded by a
caller-supplied limit. It SHALL NOT require the description to appear in the
source.

#### Scenario: Code is found by what it does
- **GIVEN** source that divides by `len(purchases)` and a repository containing
  the phrase nowhere
- **WHEN** retrieval is asked for "divides by a count that can be zero"
- **THEN** that passage is among the answers

#### Scenario: The answer is bounded
- **WHEN** retrieval is asked with a limit
- **THEN** no more than that many passages come back, nearest first

### Requirement: A retrieved passage names where it is
The system SHALL answer each passage with the path and line span it occupies,
followed by its text, in the same shape the substring channel answers in. A model
that has read either answer SHALL be able to go on to read the whole file without
learning a second convention.

#### Scenario: A hit carries its address
- **WHEN** a passage is returned
- **THEN** it is prefixed with the path and the line span it came from

### Requirement: Nothing near enough is an answer, and not reaching the index is not
The system SHALL distinguish a query that matched nothing near enough from an
index that could not be consulted. A store that cannot be reached SHALL raise
rather than answer emptily.

#### Scenario: A query with no near passage says so
- **WHEN** retrieval finds nothing above the nearness it requires
- **THEN** it answers that nothing in the source is near that description, which
  is a fact about the source

#### Scenario: An unreachable index is not an empty answer
- **WHEN** the vector store cannot be reached
- **THEN** the call fails, and does not report that the source contains nothing
  like the description

### Requirement: Retrieval states when the index is behind
The system SHALL tell a caller, with the answer, when the chunks searched
describe an earlier commit than the repository is at, naming both commits. A
caller SHALL NOT have to ask a second question to learn this.

#### Scenario: A behind index is declared with its answer
- **GIVEN** an index whose stored chunks describe an earlier commit than the
  deployed branch
- **WHEN** retrieval answers
- **THEN** the answer states that it is behind and names the commit it describes
  and the commit deployed

#### Scenario: A current index says nothing extra
- **GIVEN** an index describing the deployed commit
- **WHEN** retrieval answers
- **THEN** the answer carries the passages and no staleness notice

### Requirement: Retrieval takes no commit to search at
The system SHALL NOT accept a commit or ref to retrieve at. The index describes
one commit at a time, and a caller naming another SHALL find no way to ask for
it.

#### Scenario: There is no ref to pass
- **WHEN** the retrieval tool's parameters are enumerated
- **THEN** none of them names a commit, ref or branch
