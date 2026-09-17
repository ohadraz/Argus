# code-index Specification

## Purpose
TBD - created by archiving change 2026-09-17-rag-retrieval-for-code-fix. Update Purpose after archive.
## Requirements
### Requirement: The repository's source is held as an embedding index
The system SHALL maintain, for the Target Service's repository, an index of its
source cut into chunks and stored as embeddings in a vector store. Each chunk
SHALL carry the path it came from and the line span it occupies, so that a
retrieved passage names a place in the repository rather than only its text.

Only the service's own source SHALL be indexed. The path filter that keeps the
scenario harness out of substring search SHALL keep it out of the index, so that
the two retrieval channels answer over the same body of code.

#### Scenario: A chunk knows where it came from
- **WHEN** the repository is indexed
- **THEN** every stored chunk carries its path and its first and last line

#### Scenario: The harness is not indexed
- **GIVEN** a repository containing both the service's source and its scenario
  harness
- **WHEN** the repository is indexed
- **THEN** no chunk from a path outside the configured source paths is stored

### Requirement: Embeddings are produced locally
The system SHALL embed chunks and queries with a model running in its own
process, and SHALL make no call to an external service to do so. The embedding
call SHALL be an injected seam, so that the model can be substituted without
changing how a repository becomes an index.

This is a decision about locality, cost and the absence of an external
dependency, not about retrieval quality: a code-specialized hosted model would
retrieve better, and the trade is made deliberately.

#### Scenario: Indexing makes no external embedding call
- **WHEN** a repository is indexed
- **THEN** no request is made to any embedding service

#### Scenario: The model is substitutable
- **WHEN** indexing is constructed with a different embedding function
- **THEN** it embeds with that function, and nothing else about indexing changes

### Requirement: The index is built before an incident, never during one
The system SHALL build the index ahead of the services that read it, and SHALL
NOT build it in response to an incident. A service that reads the index SHALL NOT
begin serving until a first index has completed.

#### Scenario: The index is ready before anything queries it
- **WHEN** the system is started
- **THEN** the first index completes before any service that reads it accepts
  work

#### Scenario: An incident does not trigger indexing
- **GIVEN** an alert arrives for a repository whose index is behind
- **WHEN** the fix is proposed
- **THEN** the index is not rebuilt as part of that incident

### Requirement: The index knows which commit it describes
The system SHALL record, for the repository, the commit its stored chunks
describe and the commit the repository was last reported to be at. The two being
equal SHALL be what it means for the index to be current.

#### Scenario: A completed index records what it describes
- **WHEN** an index completes
- **THEN** the commit it indexed is recorded as what the stored chunks describe

#### Scenario: Being behind is a comparison, not a flag
- **GIVEN** a repository reported to be at a commit other than the one indexed
- **WHEN** the index's currency is asked for
- **THEN** it answers that it is behind, naming both commits

### Requirement: A push keeps the index current
The system SHALL accept notification that the deployed branch has moved, SHALL
record the commit it moved to, and SHALL bring the index up to that commit by
re-indexing the paths that changed. Notification SHALL be verified as
authentic before anything is recorded from it, and a notification about any ref
other than the deployed branch SHALL change nothing.

Bringing the index up to that commit SHALL happen away from any incident's path.

#### Scenario: An unsigned notification changes nothing
- **WHEN** a push notification arrives whose signature does not verify
- **THEN** it is rejected and no commit is recorded

#### Scenario: A push to another branch is ignored
- **WHEN** a verified push notification names a ref other than the deployed
  branch
- **THEN** nothing is recorded and the index is unchanged

#### Scenario: Only what changed is re-indexed
- **GIVEN** a verified push that added, modified or removed four files
- **WHEN** the index is reconciled
- **THEN** the chunks for those paths are replaced and the rest of the index is
  left alone

### Requirement: The index is reconciled, not driven by events
The system SHALL bring the index up to date by comparing what is indexed against
what the repository is reported to be at and acting on the difference, rather
than by processing the notifications that reported it. A notification SHALL carry
no work of its own, and reconciliation SHALL proceed on its own schedule whether
or not one arrived.

The system SHALL NOT keep a count of attempts, a backoff table or a record of
unprocessed notifications. A pass that did not complete SHALL leave the
difference in place, so the next pass attempts it again; several pushes arriving
before the index is brought up SHALL leave it converging on the most recent
commit rather than replaying each in turn.

#### Scenario: A failed pass is tried again
- **GIVEN** a pass that failed because the repository could not be read
- **WHEN** the next pass runs
- **THEN** it attempts the same commit again, with no attempt count consulted

#### Scenario: Three pushes leave one target
- **GIVEN** three pushes arrive before the index is brought up
- **WHEN** the index is reconciled
- **THEN** it indexes the third commit and does not index the first two

#### Scenario: A lost notification is not lost work
- **GIVEN** a push that never reached the system
- **WHEN** the repository's commit is next observed
- **THEN** the index is brought up to it, the missed notification costing a delay
  rather than a permanently stale index

#### Scenario: Reconciliation does not wait to be told
- **WHEN** no notification has arrived
- **THEN** the index is still compared against what the repository is at, on the
  system's own schedule

### Requirement: Indexing has one implementation
The system SHALL expose one entry point that turns a repository at a commit into
an index, optionally narrowed to named paths. A backfill and an incremental pass
SHALL both reach the index through that entry point, and no caller SHALL hold its
own account of how a repository becomes an index.

#### Scenario: Backfill and incremental are one implementation
- **WHEN** the paths by which indexing happens are enumerated
- **THEN** each of them calls the single indexing entry point and none
  reimplements chunking, embedding or storage

#### Scenario: The web application does not index
- **WHEN** the push notification is received
- **THEN** the receiving application records the commit and answers, and the
  indexing happens in another process
