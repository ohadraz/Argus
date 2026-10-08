## ADDED Requirements

### Requirement: The shop stages a scorer replica rescheduled onto a different GPU
The Target Service SHALL offer a scenario, `scorer-replica-rescheduled`, in which
one of the shop's replicas is rescheduled at the onset from a V100 node to an A100
node, with no deployment. The fraud scorer on that replica rounds as TF32 does,
which pushes purchases near the threshold over it. Every page SHALL still
return 200 at the latency it had before. The error rate, every latency quantile,
the heap and the CPU SHALL stay flat.

#### Scenario: Only the held share moves
- **GIVEN** the scenario is seeded
- **WHEN** its window is read
- **THEN** the share of purchases held for review rises after the onset, and no
  fixed signal departs

#### Scenario: No deployment sits at the onset
- **GIVEN** the scenario is seeded
- **WHEN** the deployment history is read
- **THEN** it records no revision deployed in the incident's window

### Requirement: The scorer emulates TF32 per accelerator
`io_shop` SHALL hold a pure-Python fraud scorer that takes the accelerator it
runs on. With `ALLOW_TF32` on and an Ampere accelerator it SHALL round the
scorer's inputs to TF32 precision, and otherwise it SHALL score in full
precision. Holding a purchase for review SHALL depend on no random draw.

#### Scenario: The same purchase scores differently on A100
- **GIVEN** a purchase whose score sits just below the hold threshold in full
  precision
- **WHEN** it is scored on an A100 with `ALLOW_TF32` on
- **THEN** it is held

### Requirement: The shop publishes the held share and a rule pages on it
The Target Service SHALL expose `fraud_held_for_review_ratio` in its Prometheus
exposition and answer `avg(fraud_held_for_review_ratio)` through its range-query
stand-in. It SHALL hold a rule over that query, with a `gt` threshold in
Grafana's shape, that fires when the share stays above its threshold.

#### Scenario: The rule fires on the reschedule and resolves on the pin
- **GIVEN** the scenario is seeded and its onset has passed the rule's pending
  period
- **WHEN** the rule's state is read, then the deployment is pinned to V100 and the
  rule's range and keep-firing period pass
- **THEN** it reads firing, then normal

### Requirement: The resource tree says where each replica runs
The Argo CD stand-in's resource tree SHALL list one pod per replica. Each pod
SHALL carry a `Node` info item, and the tree SHALL list `hosts` whose `labels`
carry `nvidia.com/gpu.product`. Outside this scenario every pod SHALL start at
the process's start and run on a V100 node. In it, the rescheduled pod SHALL
start at the onset on an A100 node.

#### Scenario: The rescheduled pod is the newest and on A100
- **GIVEN** the scenario is seeded
- **WHEN** the resource tree is read
- **THEN** one pod started at the onset on an A100 node, and the others started
  before it on V100 nodes

### Requirement: The stand-in accepts an accelerator pin and it ends the scenario
The Argo CD stand-in SHALL accept a merge patch of the shop Deployment's
`spec.template.spec.nodeSelector` on the GPU label, and SHALL show the selector
on the Deployment manifest. A pin to V100 SHALL end the scenario's stretch and
re-place every pod on a V100 node. A pin to any other accelerator SHALL NOT end
it. Removing the pin SHALL leave the pods where they are.

#### Scenario: Pinning to V100 ends it
- **GIVEN** the scenario is running
- **WHEN** the shop Deployment is pinned to V100
- **THEN** the held share returns to its calm level and every pod runs on V100

### Requirement: The fault Code-Fix fixes is on main and uncovered
`ALLOW_TF32 = True` SHALL be on the demo app's `main`, and no test in
`tests/io_shop` SHALL exercise the scorer on an Ampere accelerator with it on, so
that `tests/io_shop` is green at head and a fix's own test fails against `main`.

#### Scenario: The shop's own suite is green with the fault in place
- **WHEN** `tests/io_shop` runs on `main`
- **THEN** it passes
