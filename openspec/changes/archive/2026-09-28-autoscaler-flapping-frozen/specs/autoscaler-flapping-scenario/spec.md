## ADDED Requirements

### Requirement: The load is the surge's and the difference is a controller
The Target Service SHALL stage a scenario whose traffic is the demand-saturation
scenario's traffic - the same ramp to the same multiple of baseline, held - and
whose one difference is that the deployment has an autoscaler.

The multiple SHALL be the one the surge already uses, so that three replicas are
insufficient and six are comfortable. That pair is what a flap needs, and reusing
the figure keeps its sizing justified where a second figure would need its own
defence.

Nothing about the service itself SHALL change. No source is faulty, no
configuration is edited during the window, no flag moves, nothing is deployed and
no human scales anything.

#### Scenario: The traffic is the surge's
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** a metrics window is read
- **THEN** `request_volume` ramps to the same elevated level the
  demand-saturation scenario reaches, and then holds

#### Scenario: Nothing about the service changed
- **WHEN** the deploy history, the flag history and the service's own source are
  read for the window
- **THEN** no deployment landed, no flag moved, and the source is the same
  revision that served the quiet minutes

#### Scenario: Nobody scaled it
- **WHEN** the window is read and the platform is asked what has been done to the
  application
- **THEN** the replica count has changed repeatedly and no scaling was requested
  by a human or by Argus

### Requirement: The capacity a minute was served at is what moves
The Target Service SHALL report `cpu_limit_cores` as the capacity the minute was
actually **served** at, and that figure SHALL differ between minutes within one
window. It is the scenario's signature and the one series that separates this
mode from demand saturation, where the same figure is constant throughout.

`cpu_used_cores` SHALL be clamped at `cpu_limit_cores` as it is everywhere else,
so a minute served by too few replicas reports the two as equal and a minute
served by enough reports usage well below capacity. The ratio therefore
oscillates, which is the signature of a controller scaling on a metric its own
scaling changes.

The error rate and memory SHALL stay at their baselines. Nothing fails and
nothing accumulates: borrowing either signal would blur the distinction from the
leak that this mode's neighbour already exists to draw.

#### Scenario: Capacity is not the same in every minute
- **GIVEN** a window over the flapping minutes
- **WHEN** the buckets are read
- **THEN** `cpu_limit_cores` takes more than one value across them

#### Scenario: Utilisation pins in some minutes and not others
- **GIVEN** a window over the flapping minutes
- **WHEN** the buckets are read
- **THEN** some minutes report `cpu_used_cores` equal to `cpu_limit_cores` and
  others report it well below

#### Scenario: Nothing fails and nothing accumulates
- **WHEN** a window covering the incident is read
- **THEN** `error_rate` and `memory_used_bytes` are both where they were

### Requirement: The cycle is three minutes, and its shape is what the detector needs
The Target Service SHALL produce a cycle in which the deployment is served by too
few replicas for two consecutive minutes and by enough for one, repeating.

The cycle's length SHALL come from the lag a new replica takes to become ready
and start serving, which is the real reason an autoscaler thrashes: the
controller scales up on a saturated minute, the minute after is still served at
the old capacity while the new replicas warm, and only the third minute is served
at the new size - at which point utilisation has fallen and the controller scales
back down.

**The shape is arithmetic and not flavour, and the shape alone is not enough.**
An onset is dated from a run of departed minutes reaching
`anomaly_persistence_minutes`, which two elevated minutes out of every three
supplies.

Recovery needs more than the shape, and this is the requirement's load-bearing
half. How long a recovery has to hold for is measured off the incident - one minute
more than the longest lull it has already come back from - so a running cycle of two
bad minutes to one good asks for two consecutive clear minutes and supplies one. The
cycle's good minute is therefore allowed to be genuinely good, and what the shape
SHALL never supply is a lull longer than the ones the incident keeps returning from.

**The cycle SHALL be regular, and the window SHALL NOT end on a lull longer than
the cycle's own.** A regular cycle refuses a mitigation by construction whatever its
ratio: three bad minutes to two good asks for three clear ones and supplies two,
exactly as this one asks for two and supplies one. What would confirm an action that
changed nothing is therefore not a particular ratio but an irregular lull - a stretch
clear for longer than the incident has ever been seen to pause, which is what a
recovery looks like, and which is what a window frozen part-way through an unusually
long good stretch would present. That is why the shape here is arithmetic and not
flavour, and why it may not be adjusted for looks.

The alternative - a cycle whose good minute is merely less bad and never clear -
SHALL NOT be staged. The level recovery is judged against sits well above the
baseline, and the queue two saturated minutes build drains in seconds once the
replicas arrive, so a fixture holding that minute above the level would be
reporting a service no controller produces. A flapping autoscaler genuinely does
serve good minutes; a fixture that denied it would hide a defect which is real in
production and would make this scenario's own evidence a fiction.

**The requirement is on the runs that reach persistence, not on every departed
minute.** During the ramp the shop passes through merely busy on its way to
saturated, and a minute there can fall either side of the departure bar by a few
milliseconds - so the ramp is allowed a lone departed minute, and a requirement
forbidding one would assert something the fixture only mostly does, which is
worse than asserting less. What is required is that no run which *clears*
persistence is longer than the cycle's two, because that is the property recovery
is judged by.

This is the one requirement here that depends on a setting outside the fixture,
and it SHALL be stated rather than left implicit so that a reader of either finds
it. A deployment that raised `anomaly_persistence_minutes` to three would stop
this incident being detected; one that lowered it to one would let every
down-swing confirm whatever had just been tried. Neither failure announces
itself.

#### Scenario: No departed run outlasts the cycle
- **GIVEN** a window over the flapping minutes
- **WHEN** the runs of departed minutes are found
- **THEN** no run that reaches the configured persistence is longer than two
  minutes

#### Scenario: The steady state alternates
- **GIVEN** a window whose traffic has reached its plateau
- **WHEN** the minutes after the ramp are read
- **THEN** departed minutes fall in runs of two, separated by single minutes that
  did not

#### Scenario: An onset is found
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** the onset is looked for
- **THEN** one is dated, within the ramp or at the first steady pair

#### Scenario: No down-swing reads as recovery
- **GIVEN** a staged autoscaler-flapping scenario and an action taken against it
  that changes nothing
- **WHEN** recovery is judged over the minutes since that action, for as long as
  it is allowed
- **THEN** it is not confirmed

### Requirement: The scenario's live condition is the autoscaler, and each minute's count is derived
The Target Service SHALL compute each minute's telemetry from the replica count
the cycle puts in force **during that minute**, derived from the minute's position
rather than recorded as it is observed.

A derivation and not a history of resizes, which is what every other change to
this deployment's size is. The controller's resizes are not events anybody
performed, and recording them as a window is served would make the same window
read differently the second time it is fetched - which is the one property
everything generated here rests on.

The Target Service SHALL expose the autoscaler as state the platform's patch
operation changes, so the scenario reacts to whoever pins it, the demo console or
Argus, exactly as the flag scenarios react to whoever moves the flag.

A floor that has reached the ceiling SHALL stop the cycle rather than override it.
The distinction is the mechanism and not a nicety: the floor is consulted *before*
the minute's position in the cycle is computed, so for every minute after the pin
there is no cycle position at all - not a position whose answer is then replaced.
Measured at all three positions a pin can land on, including the eight minutes in
one case that the cycle had scheduled for the smaller count.

Two things follow that a spec written the other way round would get wrong. Every
minute after the pin is served at the ceiling, not merely the ones the cycle would
have given it anyway. And putting the floor back resumes the cycle at whatever
position the minute itself says, rather than where it left off, because nothing was
holding a position while it was pinned.

Minutes already served SHALL be unaffected, for the reason a resize leaves them
unaffected - a minute was served at the size the deployment had then, and erasing
that would remove the stretch a mitigation wants to be judged against at the
moment it is performed.

#### Scenario: A window read twice reads the same
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** the same window is read twice
- **THEN** every bucket is identical

#### Scenario: Pinning the floor at the ceiling ends the incident
- **GIVEN** a staged autoscaler-flapping scenario whose latency is oscillating
- **WHEN** the autoscaler's floor is raised to its ceiling, by the console or by
  Argus
- **THEN** the replica count stops changing, `cpu_used_cores` stays below
  `cpu_limit_cores`, and latency returns to its baseline and stays there

#### Scenario: Pinning does not quieten the minutes already served
- **GIVEN** a staged autoscaler-flapping scenario whose latency is oscillating
- **WHEN** the floor is raised and the whole window is read again
- **THEN** the minutes before the pin still report the capacities and the
  latencies they were served at

#### Scenario: Putting the floor back returns the service to flapping
- **GIVEN** a pinned autoscaler whose latency has recovered
- **WHEN** the floor is set back to what it was
- **THEN** the replica count resumes changing and latency oscillates again

### Requirement: Both wrong answers are refuted rather than accidentally right
The Target Service SHALL leave this scenario's telemetry unchanged by a restart,
beyond the process start time the restart moves. Demand, capacity and the
controller are all where they were, so the shop is back in the cycle from its
first served minute.

The Target Service SHALL let the autoscaler put back a replica count that Argus
sets directly. A scale-out here is the near-miss - the mode next door, reached by
a reader who saw pinned utilisation and stopped looking - and the controller
re-derives the count within the cycle, so the shop returns to flapping and the
mitigation is refuted by the fixture rather than by a rule.

That second property is what this scenario adds that no other has. Until now
nothing in the fixture ever put a replica count back, so the claim that a
mitigation taken under a live controller is a mitigation with a timer on it was
reasoned about and never demonstrated.

**The refutation SHALL hold in every phase of the cycle, not merely on average.**
A directly-set count reaches at most two consecutive clear minutes - its own
bucket, plus the cycle's next ceiling minute where it happens to land just before
one - and every stretch after it contains a run of two departed minutes. So a
settling window of any length sees a departed run before it sees three clear
minutes, whichever minute the scale-out landed in.

This is the one figure in the scenario that had to be measured rather than
reasoned about, because it is what separates a refuted scale-out from a
*confirmed* one. Had a directly-set count bought three clear minutes in any phase,
adding capacity would have been accidentally right here and the scenario would
have lost the whole of its second point.

#### Scenario: Restarting changes nothing but the start time
- **GIVEN** a staged autoscaler-flapping scenario whose latency is oscillating
- **WHEN** the service is restarted and the following minutes are read
- **THEN** `process_start_time_seconds` has changed, and the cycle and its
  latencies are where they were

#### Scenario: A scale-out is undone by the controller
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** the replica count is raised directly and the following minutes are read
- **THEN** the count returns to the cycle's, and latency goes on oscillating

#### Scenario: A mitigation taken on saturation is refuted and put back
- **GIVEN** a walk that diagnosed demand saturation here and scaled out
- **WHEN** the outcome is judged
- **THEN** the hypothesis is refuted, the count Argus set is put back, and the
  walk moves on to another candidate

### Requirement: The autoscaler is declared in the repository and live only when staged
The Target Service's deployment configuration SHALL declare the autoscaler,
including the scaling behaviour that makes it flap, so that the fault is in the
repository, is readable at the revision that is deployed, and is a thing a patch
could correct.

The **live** autoscaler SHALL be scenario state: the platform reports the
resource, and the derivation above runs, only while this scenario is staged. A
live autoscaler under every scenario would scale the demand-saturation shop out on
its own and destroy that scenario's grading - and a latent fault in the
repository that nothing is currently running is how every other fault in this
fixture is held, the shop's own source included.

#### Scenario: The fault is in the repository
- **WHEN** the deployment's configuration is read at the deployed revision
- **THEN** it declares an autoscaler whose scaling behaviour is what makes it flap

#### Scenario: No other scenario has an autoscaler
- **GIVEN** any other staged scenario
- **WHEN** the platform is asked for the application's autoscaler
- **THEN** none is reported, and the replica count changes only when somebody
  changes it

### Requirement: Reverting a flag is not an answer here, and no flag is offered as one
The Target Service SHALL stage no flag for this scenario and SHALL NOT name one as
the thing that breaks it, for the reason a leak, a surge, an upstream failure and
a bad deployment name none: a page offering a flag to watch would be offering a
control that changes nothing, and naming one would point at a suspect the fixture
invented.

#### Scenario: The scenario stages no flag
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** the flag history for the window is read
- **THEN** no flag change appears in it

#### Scenario: Moving a flag changes nothing
- **GIVEN** a staged autoscaler-flapping scenario
- **WHEN** any flag is moved and the following minutes are read
- **THEN** the telemetry is unaffected
