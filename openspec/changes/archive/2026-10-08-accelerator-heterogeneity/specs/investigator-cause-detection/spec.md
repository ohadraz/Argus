## ADDED Requirements

### Requirement: Accelerator heterogeneity is a determinable mode

The system SHALL admit `accelerator-heterogeneity` as a failure mode the
Investigator can name: the service's answers changed because a replica began
running on a different kind of accelerator, with nothing deployed.

The evidence SHALL be:
- a departure in the paging rule's series, with the five fixed signals flat;
- no revision at the onset;
- a recorded placement in which a pod started at the onset on an accelerator
  that the pods before it did not run on.

#### Scenario: A held share rising after a replica moved to A100 is accelerator heterogeneity
- **GIVEN** a window in which the rule's series - the share of purchases held for
  review - rises at the onset, the error rate, latencies and heap stay flat, no
  revision was deployed, and one pod started at the onset on an A100 node while
  the others run on V100
- **WHEN** the cause is determined
- **THEN** the mode named is `accelerator-heterogeneity`

### Requirement: Accelerator heterogeneity is separated from output-quality degradation

The mode's meaning SHALL separate it from `output-quality-degradation`, whose
change is a deployed revision at the onset. Here nothing was deployed, and what
changed is the hardware a replica runs on.

#### Scenario: The meaning names what changed
- **WHEN** the mode's meaning is read
- **THEN** it says no revision sits at the onset and a replica moved to a
  different accelerator
