# investigator-cause-detection Specification (delta)

## MODIFIED Requirements

### Requirement: A bad deployment is a determinable cause
The system SHALL include a bad deployment among the causes it can determine,
identified from a retrieved deploy event rather than inferred from log prose.
A deploy that precedes the onset and is followed by a departure the deploy
plausibly explains SHALL be attributable as that cause.

A deployment preceding the onset SHALL NOT be attributed to this cause on the
strength of being a deployment. Two causes in the taxonomy arrive as a deployment,
and this is the one in which the source code that shipped is at fault - so what
distinguishes it is what the deployment changed, which is retrievable and SHALL be
retrieved before the two are told apart.

#### Scenario: A deploy before a latency departure is attributed
- **GIVEN** the Target Service's active scenario is `bad-deployment`, whose
  deploy precedes a p95 latency departure
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as a bad deployment, at a confidence high
  enough to route to `mitigating`

#### Scenario: A flag-caused incident is not attributed to a deploy
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`, for
  which the change source reports no deploy
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as the feature flag toggle, not as a
  deployment

#### Scenario: A deployment that changed no source code is not a bad deployment
- **GIVEN** an incident preceded by a deployment whose change touches no source
  file
- **WHEN** the Investigator investigates the incident
- **THEN** it does not determine the cause as a bad deployment

## ADDED Requirements

### Requirement: A configuration-induced failure is a determinable cause

The system SHALL include a configuration-induced failure among the causes it can
determine, and SHALL separate it from a bad deployment by what the deployment
changed: the source code that shipped, or the configuration values it shipped
with.

The separation SHALL NOT rest on the path a deployment shipped from. That path
names where a deployment's manifests live and is the same directory whatever the
commit touched, so it is constant across the distinction it would be asked to
make.

The model SHALL be told which channel answers the question rather than told what
to conclude. What separates the pair is a fact about a commit, and pointing a
model at a fact it can retrieve is different in kind from handing it a rule to
apply to evidence it already has.

#### Scenario: A configuration value that moved is attributed as a configuration-induced failure
- **GIVEN** the Target Service's active scenario is `cache-misconfigured`, whose
  deployment changes one value in a configuration file and no source file
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as a configuration-induced failure, at a
  confidence high enough to route to `mitigating`

#### Scenario: Two deployments shipping from the same path reach different causes
- **GIVEN** two incidents, each preceded by a deployment from the same source
  path, one whose commit changed a configuration value and one whose commit
  changed source code
- **WHEN** the Investigator investigates each
- **THEN** the first is determined as a configuration-induced failure and the
  second as a bad deployment

#### Scenario: The subject names the configuration that changed
- **GIVEN** an incident determined as a configuration-induced failure
- **WHEN** the hypothesis is inspected
- **THEN** its subject names the configuration the deployment changed, as the
  evidence spells it
