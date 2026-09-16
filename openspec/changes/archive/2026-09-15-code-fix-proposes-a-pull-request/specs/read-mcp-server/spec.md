## ADDED Requirements

### Requirement: The service's own source is a read channel
The system SHALL serve the Target Service's repository as two read tools - what
files there are at a ref, and what one of them says - under a credential that
can read a repository and cannot write to one. A repository becoming visible to
the read tier SHALL NOT make the read tier capable of changing it (§13).

#### Scenario: The files of a repository are listed
- **WHEN** the repository is listed at a ref
- **THEN** every file is named as a path from the root, and directories are left
  out

#### Scenario: A file is read as the text it holds
- **WHEN** a path is read at a ref
- **THEN** its whole contents come back as text

#### Scenario: The read credential cannot write
- **WHEN** the read tier's configuration is examined
- **THEN** the credential it holds for the repository grants reading only, and
  no tool on this server changes a repository

### Requirement: A listing that is not whole is refused
The system SHALL raise rather than answer when the repository could not be read
in full - including when the provider truncated its own listing. A listing
missing files is indistinguishable from a repository that does not have them,
and a fix would be written for the wrong file.

#### Scenario: A truncated listing is refused
- **GIVEN** a repository large enough that the provider truncates its answer
- **WHEN** the files are listed
- **THEN** the call fails, naming the truncation, rather than returning a short
  list

#### Scenario: A path that is not there is said to be missing
- **WHEN** a path that does not exist is read
- **THEN** the call fails, rather than answering with an empty string - a file
  that exists and says nothing is a real thing, and the two must not arrive
  looking alike

#### Scenario: A file that is not text is refused
- **WHEN** a path holding an image or an archive is read
- **THEN** the call fails rather than returning replacement characters that
  reach a model looking like code
