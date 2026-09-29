## ADDED Requirements

### Requirement: A deployment that landed and stopped half-way
The Target Service SHALL stage a scenario in which a revision was deployed and
its rolling update was paused part way, so that the fleet is split: some replicas
serving the deployed revision and the rest still serving the one before it.

The split SHALL be even, and SHALL hold for the whole window. A mixture that
drifted minute by minute would be a second flapping scenario, and the point here
is a state nothing in the estate is moving towards or away from.

The pause SHALL be the reason it holds. Pausing a rolling update is a first-class
and ordinary thing to do to a Deployment - somebody sends half the fleet to a new
revision to watch it - and it is what makes the scenario's condition live rather
than arbitrary: the platform is not converging because it was told to stop.

Nothing else about the service SHALL be wrong. No flag moves, no configuration is
edited during the window, the process is healthy, the cache is up and answering,
and no neighbour is slow.

#### Scenario: Two revisions are serving at once
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the platform is asked about the application's Deployment
- **THEN** it reports replicas on two revisions, and reports the rolling update as
  paused

#### Scenario: A deployment landed at the onset
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the deploy history for the window is read
- **THEN** it holds one entry, at the onset, naming the revision being rolled out

#### Scenario: Nothing else changed
- **WHEN** the flag history for the window is read and the process is inspected
- **THEN** no flag moved and the process has been up since before the window
  opened

### Requirement: The failing share is the product of two shares
The Target Service SHALL fail an account page when a replica on the older side
reads a summary-cache entry a replica on the newer side wrote, and SHALL NOT fail
it otherwise.

The deployed revision changes the shape of what the summary cache stores. The
newer side writes the new shape and reads only the new shape; the older side
cannot read a shape that did not exist when it was written. The incompatibility
SHALL be one-directional, so that the diff shows a writer that changed and a
reader that was never taught the old shape - which is the missing expand step of
an expand-contract migration, stated in code.

The failing share SHALL therefore be the product of the share of entries written
by the newer side and the share of reads taken by the older one, scaled by how
much of the traffic the cache answers at all. It SHALL be zero before the rollout
begins, zero once it converges, and largest in the middle - which is the
arithmetic no other mode in the catalogue produces, and which a reader can check.

#### Scenario: The error rate moves and the quantiles do not
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** a window covering the incident is read
- **THEN** `error_rate` is elevated and `p50_ms`, `p95_ms` and `p99_ms` are all at
  their baselines

#### Scenario: The cache is healthy throughout
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the window is read
- **THEN** `cache_hit_ratio` is at the ratio a working cache reports, unchanged
  from the quiet minutes

#### Scenario: Nothing accumulates and nothing saturates
- **WHEN** a window covering the incident is read
- **THEN** `memory_used_bytes` and `cpu_used_cores` are both where they were, and
  `cpu_limit_cores` holds one value across the window

#### Scenario: The failures say what they are
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the log lines for the window are read
- **THEN** they report a summary-cache entry that could not be read, and name
  neither a flag nor a release

### Requirement: Its telemetry is the flag scenario's, and the change channel is what separates them
The Target Service SHALL produce, for this scenario, the shape a feature-flag
incident produces: an error rate that steps and latency that does not move at
all.

That collision is deliberate and is the scenario's difficulty. What separates the
two is the change channel and nothing else - a flag moved for one, a deployment
landed for the other - and what then separates this from a bad deployment is that
the deployment did not finish, which is a fact about the rollout rather than
about the code it carried.

#### Scenario: The shape alone does not name the mode
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the metrics alone are read
- **THEN** they are indistinguishable from a feature-flag incident's, and the flag
  history is empty

### Requirement: Both revisions are correct, and the fixture proves it
The Target Service's own tests SHALL pass at the revision deployed and at the
revision before it. Neither commit is faulty; what is faulty is that both are
serving.

Both revisions SHALL be real commits in the Target Service's repository, pushed
before anything reads them, and their hashes SHALL be constants in the scenario
definition - as the cache port's commit and the slow average's are. The diff
between them is the diagnosis, and it is read from the repository rather than
described in the scenario's own words.

#### Scenario: Each side passes its own tests
- **WHEN** the Target Service's tests are run at the deployed revision and at the
  revision before it
- **THEN** both are green

#### Scenario: The diff shows the writer and not a defect
- **WHEN** what the deployment changed is read
- **THEN** it names the summary-cache module, and shows a stored shape that
  changed with no read path kept for the old one

### Requirement: Converging the fleet ends it, and a restart does not
The Target Service SHALL end the incident when the deployment is returned to the
revision before it, because that puts every replica on one version - and one
version reading and writing one shape is a shop that works, whichever version it
is.

The Target Service SHALL leave this scenario's telemetry unchanged by a restart,
beyond the process start time the restart moves. The fleet is still split when
the process comes back, and nothing about the split is the process's doing.

No flag SHALL be staged and none SHALL be named as the thing that breaks it, for
the reason a leak, a surge, a bad deployment and a flapping controller name none:
a page offering a flag to watch would be offering a control that changes nothing.

#### Scenario: Rolling the deployment back ends it
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the deployment is returned to the revision before it, by the console or
  by Argus
- **THEN** every replica reports one revision, the error rate returns to its
  baseline, and it stays there

#### Scenario: Restarting changes nothing but the start time
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** the service is restarted and the following minutes are read
- **THEN** `process_start_time_seconds` has changed and the error rate is where it
  was

#### Scenario: Moving a flag changes nothing
- **GIVEN** a staged half-finished-rollout scenario
- **WHEN** any flag is moved and the following minutes are read
- **THEN** the telemetry is unaffected

#### Scenario: The minutes already served keep their failures
- **GIVEN** a staged half-finished-rollout scenario that has been rolled back
- **WHEN** the whole window is read again
- **THEN** the minutes before the rollback still report the error rate they were
  served at

### Requirement: Mitigated, never resolved
The Target Service SHALL leave the repository declaring the revision that was
being rolled out, so that a rollback ends the incident without ending the
condition. Re-enabling the platform's own reconciliation SHALL bring the rollout
back, and a withdrawal SHALL return the shop to a rollout stopped half-way.

What is left to fix afterwards is not a file. The migration needed a version that
could read both shapes before one that wrote only the new one, and no patch of
either revision supplies that.

#### Scenario: The repository still asks for the revision
- **GIVEN** a rolled-back half-finished-rollout scenario
- **WHEN** the configuration repository is read
- **THEN** it still declares the revision that was being rolled out

#### Scenario: A withdrawal returns the shop to the mixture
- **GIVEN** a rolled-back half-finished-rollout scenario whose error rate has
  recovered
- **WHEN** the rollback is withdrawn
- **THEN** the fleet is split again and the error rate returns
