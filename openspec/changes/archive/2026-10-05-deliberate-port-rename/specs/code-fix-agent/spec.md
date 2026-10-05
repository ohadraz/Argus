## ADDED Requirements

### Requirement: The deployment's configuration is part of what the agent can find

The source scope the agent lists and searches SHALL include the directory holding
the service's deployment configuration, alongside its source and its tests. A
fault in a values file or a scrape configuration is a fault in the service as
deployed, and a fix the agent cannot find the file for is one it guesses at.
Both retrieval channels SHALL answer the same scope.

#### Scenario: A configuration file is listed
- **WHEN** the agent lists the repository's files
- **THEN** the files under the deployment configuration directory are among them

#### Scenario: A configuration file is found by search
- **WHEN** the agent searches for a string that appears only in the scrape
  configuration
- **THEN** that file is returned
