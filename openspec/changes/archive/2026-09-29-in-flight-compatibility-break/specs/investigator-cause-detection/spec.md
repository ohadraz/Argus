## ADDED Requirements

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
