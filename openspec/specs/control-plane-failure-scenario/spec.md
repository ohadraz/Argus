# control-plane-failure-scenario Specification

## Purpose
The staged incident in which the platform four of Argus's five mitigations act
through will not act. A cause with candidates on two platforms, the deployment
rollback ranked above the feature flag revert, and a deployment platform that
refuses everything that changes state while going on reporting what it holds - so
that narrowing the walk to the platform still answering is what has to happen for
the incident to be mitigated at all.

## Requirements

### Requirement: The scenario stages a cause with candidates on two platforms

The scenario SHALL stage an incident in which both a deployment and a feature
flag moved inside the window the investigation reads, such that the ranked
candidates include a deployment rollback above a feature flag revert.

Two platforms in one incident is what the scenario exists for. A cause whose
every candidate acts through the failed platform cannot tell a walk that narrows
itself to what is reachable from a walk that stops at the first failure - both
escalate, and the scenario would pass without exercising the thing it is named
for.

The deployment ranked first, because the fall-through has to be the walk's doing
rather than the ordering's. A flag revert already ranked first would be taken
before the deployment platform was ever reached for.

#### Scenario: Both a deployment and a flag moved in the window
- **GIVEN** the scenario is armed
- **WHEN** the change channels are read for the incident's window
- **THEN** both a deployment and a feature flag change are found in it

#### Scenario: The rollback outranks the flag revert
- **GIVEN** the scenario is armed and the incident investigated
- **WHEN** the candidates are ranked
- **THEN** a deployment rollback stands above a feature flag revert

### Requirement: The deployment platform cannot be acted through and can still be read

The scenario SHALL make the Target Environment refuse the deployment platform's
state-changing routes while its reporting routes keep answering, and SHALL leave
the Target Service serving and reporting its own metrics throughout.

A platform Argus cannot *see* is a different incident. The deployment history is
read from the same platform, so refusing every route would hide the deployment
that is this incident's first candidate: no rollback would be ranked, the walk
would never reach for the platform, and the case would pass without exercising
anything it exists for.

The shop staying up matters for its own reason. If the service were down too, no
verification could judge any mitigation and the incident would end for that
instead.

#### Scenario: The acting routes refuse and the reporting routes answer
- **GIVEN** the scenario is armed
- **WHEN** the deployment platform is asked to change something, and separately
  asked for an application's state
- **THEN** the first is refused and the second answers

#### Scenario: The shop is unaffected
- **GIVEN** the scenario is armed
- **WHEN** the Target Service is asked to serve and for its metrics
- **THEN** it does both

### Requirement: The incident is mitigated through the reachable platform

The walk SHALL reach for the deployment rollback, find the deployment platform
unreachable, pass over every remaining candidate on that platform, take the
feature flag revert, and end with the incident `MITIGATED`.

#### Scenario: The flag revert is what ends the incident
- **GIVEN** the scenario is armed
- **WHEN** the incident is walked to a terminal status
- **THEN** the flag revert was taken, the rollback was not, and the incident is
  `MITIGATED`

#### Scenario: The record says why the rollback did not happen
- **GIVEN** a walked incident from this scenario
- **WHEN** its events are read
- **THEN** one of them records the deployment platform as unreachable
