## ADDED Requirements

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
