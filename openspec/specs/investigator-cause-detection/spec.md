# investigator-cause-detection Specification

## Purpose
TBD - created by archiving change investigator-hypothesis-loop. Update Purpose after archive.
## Requirements
### Requirement: Investigator determines failure_mode from the Target Service's current logs
The system SHALL make the `argus-read-mcp` server's `get_log_lines` and
`get_change_events` tools available to the model during investigation, and SHALL
dispatch them when the model calls them. It SHALL determine a `failure_mode`
by asking a real LLM to judge the evidence it retrieved - metrics, logs and
changes, whichever of them it chose to read. Deterministic keyword matching SHALL NOT be
the mechanism, and the model SHALL NOT be the thing that parses a change source's
response: a tool result SHALL reach the model already typed.
An undetermined cause SHALL be reported at a confidence below the mitigate
threshold.

#### Scenario: Feature-flag-toggle logs are recognized
- **GIVEN** the Target Service's active scenario is `feature-flag-toggle`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `failure_mode = "feature-flag-toggle"` at a confidence
  high enough to route to `mitigating`

#### Scenario: No recognizable logs report an undetermined cause, not a confident one
- **GIVEN** the Target Service has no active scenario (`get_log_lines`
  returns an empty list)
- **WHEN** the Investigator investigates the incident
- **THEN** it records a hypothesis with `failure_mode` left undetermined
  (`NULL`), at a confidence below the mitigate threshold, and the incident
  routes to `escalated` rather than to `mitigating`

#### Scenario: A cause is determinable without every channel being read
- **GIVEN** an incident whose change events account for the departure on their own
- **WHEN** the model answers having read changes and metrics but not logs
- **THEN** the determined `failure_mode` is accepted, and the unread channel is not
  treated as missing evidence

### Requirement: failure_mode is persisted on the hypothesis row
The system SHALL write the determined `failure_mode` (or leave it `NULL` if undetermined) to the `hypothesis` table's `failure_mode` column, in addition to `description` and `confidence`.

#### Scenario: A determined cause is persisted
- **GIVEN** the Investigator determines `failure_mode = "feature-flag-toggle"` for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the `hypothesis` row for that incident has `failure_mode = 'feature-flag-toggle'`

### Requirement: The evidence behind a cause determination is recorded
The system SHALL record which retrieved evidence the verdict relied on, so a
human picking up the incident can tell what the determination was based on and
distinguish a well-evidenced call from a thin one. Since which channels were read is
the model's choice, the record SHALL also make plain what was retrieved and what was
not.

#### Scenario: Supporting evidence accompanies a determined cause
- **GIVEN** the Investigator determines a cause for an incident
- **WHEN** the hypothesis is recorded
- **THEN** the evidence the verdict relied on is recorded with it

#### Scenario: What was never read is distinguishable from what came back empty
- **GIVEN** an investigation in which the model never called the change-events tool
- **WHEN** the incident's record is examined
- **THEN** it shows that channel as unread, not as read and empty

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

### Requirement: A change alone is not a cause
The system SHALL treat a retrieved change as a candidate explanation to be
judged against the symptoms, not as proof of causation. A change that does not
explain the observed departure SHALL NOT be reported as the cause merely
because it is the only change in the window.

#### Scenario: An unrelated change does not become the verdict
- **GIVEN** evidence containing a change that does not account for the
  observed symptoms
- **WHEN** the Investigator investigates
- **THEN** it does not report that change as the cause, and reporting no
  determined cause remains available

### Requirement: An upstream dependency failure is a determinable failure mode
The system SHALL carry `upstream-dependency-failure` in the closed set of
failure modes, and the Investigator SHALL be able to determine it from the
evidence it retrieves: failures that name a third party, latency that moved
with the errors, and no change of Argus's own to account for either.

A determination of this mode SHALL be recorded at a confidence read the same
way every other mode's is. It SHALL NOT be treated as an undetermined cause -
the mode is known, and what follows from it is a decision rather than a gap.

#### Scenario: Upstream failures are recognised
- **GIVEN** the Target Service's active scenario is `upstream-dependency-failure`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines `failure_mode = "upstream-dependency-failure"` and
  records the evidence it relied on

#### Scenario: A determined upstream cause is not an undetermined one
- **GIVEN** the Investigator determined `upstream-dependency-failure`
- **WHEN** the hypothesis is recorded
- **THEN** `failure_mode` is that value rather than `NULL`, and the incident is
  not recorded as a cause nobody could determine

### Requirement: An internal dependency's failure is a determinable cause
The system SHALL include the failure of a service the organisation owns and the
alerting service calls among the causes it can determine, and SHALL make the
service catalogue available to the model during investigation so that the
determination rests on retrieved ownership rather than on the dependency's name.

A propagation incident SHALL be attributable to the correct side of that line:
the same shape of evidence - the caller's own logs blaming something else - is
`upstream-dependency-failure` when the catalogue says the dependency belongs to
somebody else, and `internal-dependency-failure` when it says the organisation
owns it.

#### Scenario: An owned dependency's slowness is attributed to it
- **GIVEN** the Target Service's active scenario is `pricing-service-degraded`,
  whose logs attribute the request time to a dependency the catalogue marks as
  owned
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as an internal dependency's failure, at a
  confidence high enough to route to `mitigating`

#### Scenario: A third party's failure is not attributed to an internal dependency
- **GIVEN** the Target Service's active scenario is
  `upstream-dependency-failure`, whose logs name a dependency the catalogue
  marks as not owned
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the cause as an upstream dependency's failure, not as
  an internal one

#### Scenario: An incident with no deploy is not attributed to one
- **GIVEN** the Target Service's active scenario is `pricing-service-degraded`,
  for which the change source reports no deploy and no flag moved
- **WHEN** the Investigator investigates the incident
- **THEN** it does not determine the cause as a bad deployment

### Requirement: Determining an internal dependency's failure obliges naming the service
The system SHALL require a hypothesis determining an internal dependency's
failure to name the service at fault, in the field that carries an address
rather than in the subject or in prose. A determination of that mode naming no
service SHALL be recorded as it was answered and SHALL reach the mitigation as
a cause nothing could be proposed for, rather than being acted on against the
alerting service.

#### Scenario: The determined cause names the dependency
- **GIVEN** an investigation concluding that a named dependency is at fault
- **WHEN** the hypothesis is recorded
- **THEN** the dependency's name is on the hypothesis as the service at fault

#### Scenario: A mode of this kind without a service is not acted on
- **GIVEN** a hypothesis determining an internal dependency's failure and naming
  no service
- **WHEN** the walk reaches the mitigation
- **THEN** no action is taken, and in particular the alerting service is not
  restarted in the absence of an address

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

### Requirement: Demand saturation is a determinable failure mode

The system SHALL include demand saturation among the modes it can determine, and
SHALL separate it from a resource leak by whether consumption moved with the
traffic. A leak climbs while the traffic does not; a saturated service consumes
what its traffic asks of it, and what has changed is how much is being asked.

The separation SHALL rest on evidence the Investigator retrieves rather than on a
rule it is handed. The volume and the utilisation are both on the bucket beside
the quantiles, so the model is told which fields answer the question and left to
read them - which is the same treatment the pair of deployment modes get, and for
the same reason.

The system SHALL separate it from a bad deployment and from a dependency's
failure by the change channels being empty and by where the time goes. Every one
of the three moves the median, the 95th and the 99th together; what distinguishes
this one is that nothing was deployed, no flag moved, and the requests are slow
in the service's own work rather than waiting on somebody else's.

#### Scenario: Consumption that moved with the traffic is not attributed to a leak
- **GIVEN** the Target Service's active scenario is `cpu-saturation`, whose
  reported volume climbs while its heap stays flat
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as demand saturation, at a confidence high
  enough to route to `mitigating`

#### Scenario: A leak is still determined where the traffic did not move
- **GIVEN** the Target Service's active scenario is `resource-leak`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as a resource leak, unchanged by the arrival of
  the mode beside it

#### Scenario: A saturated service is not attributed to a deployment
- **GIVEN** an incident in which every quantile climbed together and the deploy
  history over the window is empty
- **WHEN** the Investigator investigates it
- **THEN** it does not determine a bad deployment, and its account says the
  change channels carried nothing

#### Scenario: The subject names the resource that ran out
- **GIVEN** an incident determined as demand saturation
- **WHEN** the hypothesis is inspected
- **THEN** its subject names the resource the evidence shows exhausted, as the
  evidence spells it

### Requirement: Autoscaling pathology is a determinable failure mode

The system SHALL include autoscaling pathology among the modes it can determine,
and SHALL separate it from demand saturation by whether the capacity is itself
moving. A saturated service has a fixed capacity its load outgrew; this one has a
capacity that will not settle, and the load never had to grow at all for it to
degrade.

The separation SHALL rest on evidence the Investigator retrieves rather than on a
rule it is handed. `cpu_limit_cores` is on every bucket beside the usage and the
quantiles, so a capacity that takes more than one value across a window is
readable without a new tool - which is the same treatment the pair of deployment
modes and the pair of capacity modes already get.

The system SHALL hold this mode to the same discipline the near-miss makes
necessary: at the bottom of every cycle the evidence is demand saturation's
evidence exactly. A determination of saturation is therefore the failure to look
at one series rather than a different reading of the same ones, and the mode's
meaning SHALL say which series that is.

The system SHALL separate it from a bad deployment, a configuration change and a
dependency's failure the way saturation is separated from all three - the change
channels are empty and the time is spent in the service's own work - and SHALL
NOT require a human's scaling to be ruled out by anything other than its absence
from the record.

#### Scenario: A moving capacity is not attributed to saturation
- **GIVEN** the Target Service's active scenario is `autoscaler-flapping`, whose
  `cpu_limit_cores` takes more than one value across the window
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as autoscaling pathology, at a confidence high
  enough to route to `mitigating`

#### Scenario: Saturation is still determined where the capacity held still
- **GIVEN** the Target Service's active scenario is `cpu-saturation`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as demand saturation, unchanged by the arrival
  of the mode beside it

#### Scenario: A flapping deployment is not attributed to a deployment or a flag
- **GIVEN** an incident in which the capacity oscillated and the deploy history
  and flag history over the window are both empty
- **WHEN** the Investigator investigates it
- **THEN** it determines neither a bad deployment nor a flag toggle, and its
  account says the change channels carried nothing

#### Scenario: The account says what is moving
- **GIVEN** an incident determined as autoscaling pathology
- **WHEN** the hypothesis is inspected
- **THEN** its account cites the capacity series and says it changed within the
  window, as the evidence spells it


### Requirement: An in-flight compatibility break is a determinable failure mode

The system SHALL include in-flight compatibility break among the modes it can
determine, and SHALL separate it from a bad deployment by whether the deployment
finished arriving. There a revision landed and the code it carried is wrong; here
a revision landed and stopped half-way, and what fails is the requests that cross
between the two versions now serving.

The separation SHALL rest on evidence the Investigator retrieves rather than on a
rule it is handed, and the evidence is a channel rather than a series: the deploy
history says a revision was deployed and cannot say whether it converged, so the
rollout the platform is running has to be asked about directly.

The system SHALL hold this mode to the discipline its two near-misses make
necessary, because it has one on either side. Its metrics are a feature-flag
incident's - an error rate that steps with every quantile flat - so the flag
history has to be read before the shape is believed. Its change channel is a bad
deployment's - one entry, at the onset - so the rollout has to be read before the
revision is blamed.

The system SHALL NOT require that a culprit revision be named. This is the one
mode in the set where no revision is at fault, and an account that named one
would be wrong in the way this mode exists to prevent: a postmortem filing a fix
against code with no defect in it, and saying nothing about the rollout that was
left half-done.

#### Scenario: A rollout that did not converge is not attributed to the revision
- **GIVEN** the Target Service's active scenario is `half-finished-rollout`, whose
  deployment landed at the onset and is still split across two revisions
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as an in-flight compatibility break, at a
  confidence high enough to route to `mitigating`

#### Scenario: A bad deployment is still determined where the rollout converged
- **GIVEN** the Target Service's active scenario is `bad-deployment`
- **WHEN** the Investigator investigates the incident
- **THEN** it determines the mode as a bad deployment, unchanged by the arrival of
  the mode beside it

#### Scenario: A stepped error rate with no flag moved is not attributed to a flag
- **GIVEN** an incident whose error rate stepped, whose quantiles are flat, and
  whose flag history over the window is empty
- **WHEN** the Investigator investigates it
- **THEN** it determines no flag toggle, and its account says the flag channel
  carried nothing

#### Scenario: The account says the rollout is what is wrong
- **GIVEN** an incident determined as an in-flight compatibility break
- **WHEN** the hypothesis is inspected
- **THEN** its account cites the rollout as unconverged and attributes the failure
  to two versions serving at once, rather than to either of them
