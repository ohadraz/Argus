## ADDED Requirements

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
