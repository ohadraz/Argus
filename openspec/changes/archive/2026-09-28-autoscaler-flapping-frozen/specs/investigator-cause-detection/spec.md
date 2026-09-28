## ADDED Requirements

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
