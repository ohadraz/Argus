## ADDED Requirements

### Requirement: Autoscaling pathology is a failure mode of its own
The system SHALL carry a failure mode for a deployment whose replica count is
being moved by its own autoscaler in a way that degrades it, distinct from demand
saturation. The two are the halves of capacity's share and they are separated by
what is wrong: there a fixed capacity was outgrown by the load, and here the
capacity itself will not settle. Since what dispatches on a mode is the choice of
mitigation, they are two modes - one is answered by adding capacity and the other
by stopping the thing that keeps taking it away.

It is the first mode whose fault is a control loop rather than a change or a
state. That is what separates it from every other mode at the level a reader
works: nothing was deployed, no value was edited, no flag moved, and no human
scaled anything - and yet the deployment is a different size every minute.

The meaning that travels with the mode into the tool schema SHALL say what
separates it from its nearest neighbour. From demand saturation, that the
capacity a minute was served at is itself moving, where saturation is a fixed
capacity the load exceeded. The distinction SHALL be stated in terms of a series
a reader can retrieve, because at the bottom of every cycle this mode's telemetry
is saturation's telemetry exactly.

#### Scenario: The mode maps to the pinning strategy
- **GIVEN** a hypothesis determining autoscaling pathology
- **WHEN** a mitigation is proposed for it
- **THEN** a pin of the application's autoscaler is proposed

#### Scenario: Saturation and a flapping autoscaler reach different mitigations
- **GIVEN** two hypotheses, one determining demand saturation and one determining
  autoscaling pathology
- **WHEN** a mitigation is proposed for each
- **THEN** the first proposes a scale-out and the second a pin

### Requirement: Pinning an autoscaler is a mitigation Argus can take
The system SHALL offer, on the write tier, a tool that raises a deployment's
autoscaler floor to that autoscaler's own ceiling. It SHALL belong to the
declared set of generic mitigations, so it is taken without approval - on the
same ground the other four are, that it is a routine, well-understood procedure
applied before the cause is fully understood.

It SHALL be the first mitigation that stops something rather than adding or
restoring something, and the set's criterion SHALL be unchanged by that: what
admits an action is membership of the set, never what kind of change it is.

The autoscaler SHALL be left in place. Pinning is one field, and the controller
goes on running with no room to scale down; removing it would be a resource
somebody has to recreate from a manifest, and the system SHALL NOT delete what it
cannot put back in the same call.

The system SHALL NOT offer the reverse of a pin as a mitigation - lowering a
floor, or lowering a ceiling. Either reduces capacity, and being wrong about
adding capacity costs money where being wrong about removing it costs an outage.

#### Scenario: A pin proceeds without approval
- **GIVEN** a proposed pin of the alerting service's autoscaler
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, and the action is announced and recorded

#### Scenario: The autoscaler survives the mitigation
- **WHEN** a pin is performed
- **THEN** the autoscaler still exists, with its ceiling unchanged, and no
  resource was deleted

### Requirement: A deployment an autoscaler owns is not scaled directly
The system SHALL perform a pin by patching the live autoscaler, and SHALL NOT
perform it by setting the deployment's replica count.

A live autoscaler owns that count and re-derives it from its own metric within a
sync period, so a write to the deployment is undone by the controller - which is
the incident rather than the answer to it. This is the general form of the rule
the scale-out already follows for a GitOps controller: **anything that re-derives
the state a mitigation just set has to be suspended or changed before it is set**,
and an autoscaler and a repository are two such things.

The patch SHALL be addressed to the autoscaler by group, version and kind, and
SHALL change one field. A patch that rewrote the resource would be a manifest
Argus authored, which is the thing no generic mitigation does.

#### Scenario: The controller is what is written to
- **WHEN** a pin is performed
- **THEN** the autoscaler is patched, and the deployment's replica count is not
  set by Argus

#### Scenario: One field changes
- **GIVEN** an autoscaler with a floor, a ceiling, a target and a scaling
  behaviour
- **WHEN** a pin is performed
- **THEN** only the floor differs afterwards

### Requirement: The count to pin at is the tier's to resolve, and it is the ceiling
The system SHALL NOT carry a replica count on the proposed action. The action
SHALL name the application alone, and the tier that performs it SHALL read the
autoscaler's own bounds, derive the floor to set from them, and report back what
the floor was and what it is now.

The floor SHALL be set to the autoscaler's **ceiling** and not to the count
currently in force. A flapping deployment's live count is a coin toss: read at
the bottom of the cycle it is the count that is too small, and pinning there
would hold the service in the state the incident is made of and then judge a
mitigation against it. The ceiling is also the only number available that Argus
is not inventing - a bound a human declared for this deployment, read from the
live resource, exactly as a scale-out reads the count it doubles.

The bounds SHALL be read from the platform's live resource rather than from the
repository's configuration, for the reason a scale-out reads its count there:
what the repository holds is what the platform is asked to converge on, which is
a different thing from what is in force.

**Where the autoscaler is SHALL be asked of the platform and never configured.**
The name and the namespace SHALL be read from the platform's own listing of what
is running under the application, and no setting SHALL carry either. A namespace
held as configuration is a second copy of a fact the platform can state, which can
only ever be right by agreement and is wrong the moment an application moves - and
it is a worse failure than a wrong count, because a patch addressed into a
namespace the resource is not in does not fail loudly. It matches nothing, changes
nothing, and reports success, so Argus records a mitigation as taken and then
judges the service against it.

It is read from the listing rather than from the resource itself, and the order is
forced rather than chosen: fetching the resource requires naming where it is, so
there would be nothing to read a namespace from yet. **A pin asks where the
autoscaler is before it asks what the autoscaler says.**

The autoscaler SHALL NOT be assumed to be named after the application it scales.
Nothing requires the two to match, so a tier that sent the application's name
would be right only where somebody happened to spell them alike.

This is not the rule a restart follows, and the difference is real rather than an
inconsistency to be tidied away. A restart may be aimed at a dependency whose
listing the tier never reads - the alerting service is well and the action is
addressed elsewhere - so it has nothing in hand to take a namespace from. A pin
has asked about its own target before it writes.

#### Scenario: The action carries no number
- **WHEN** a pin is proposed
- **THEN** it names the application and carries no replica count

#### Scenario: Both floors are reported back
- **GIVEN** an autoscaler with a floor of three and a ceiling of six
- **WHEN** a pin is performed
- **THEN** the result says the floor was three and is now six

#### Scenario: The cycle's position does not decide the count
- **GIVEN** a flapping autoscaler read at a minute when three replicas are
  serving, and the same autoscaler read at a minute when six are
- **WHEN** a pin is performed in each case
- **THEN** both pin at the ceiling

#### Scenario: The location is the one the platform reported
- **GIVEN** an autoscaler the platform lists under the application, in a namespace
  and under a name of its own
- **WHEN** a pin is performed
- **THEN** the patch is addressed to that name and that namespace, and no
  configured value decides either

#### Scenario: An autoscaler named after something else is still found
- **GIVEN** an autoscaler whose name is not the application's
- **WHEN** a pin is performed
- **THEN** it is addressed to the name the platform reported

### Requirement: A pin is bounded by how far it may go
The system SHALL bound the replica count a pin may reach, SHALL clamp a ceiling
above that bound rather than obeying it, and SHALL refuse a pin that would change
nothing. The bound SHALL be the same one a scale-out is held to, and SHALL be
held by the tier that performs the action - it is a fact about the estate rather
than about the incident, and two bounds on one estate's capacity would be two
figures to keep level.

An autoscaler declaring a ceiling Argus may not reach is a declaration about the
deployment, not a permission. The system SHALL pin at its own bound in that case
and SHALL say that it did.

A floor already at the ceiling is not a pathology this can answer: the count is
not moving, so there is nothing to stop. It SHALL be refused rather than
performed as a no-op, so that the walk moves on to another candidate or escalates
instead of waiting to be judged against a change that never happened.

#### Scenario: A ceiling above the bound is clamped
- **GIVEN** an autoscaler whose ceiling exceeds the most replicas Argus may ask
  for
- **WHEN** a pin is performed
- **THEN** the floor is raised to Argus's bound and the result says so

#### Scenario: An autoscaler that is already pinned is refused
- **GIVEN** an autoscaler whose floor already equals its ceiling
- **WHEN** a pin is proposed
- **THEN** it is refused, the refusal says the count is not moving, and the walk
  moves on to another candidate or escalates

### Requirement: Automated sync is suspended for the pin and restored by the undo
The system SHALL suspend the platform's automated reconciliation of the
application before patching its autoscaler, and SHALL record whether
reconciliation was in force as it was found. A GitOps controller re-applies the
autoscaler's manifest at its next sync, back to the floor the repository holds -
so a pin taken under automated sync is a mitigation with a timer on it, and the
service would return to flapping at a moment nothing in the record explains.

The undo SHALL therefore restore two things: the floor the autoscaler had, and
the reconciliation setting as it was found. The setting SHALL never be restored
to a default - an application somebody had already stopped reconciling is left
stopped, because Argus does not turn on a thing it did not turn off.

The undo SHALL put the floor back before restoring reconciliation. Restoring sync
first would have the platform set the floor back on its own, to the same number,
unverifiably, at a moment nothing here chose.

#### Scenario: A pin suspends reconciliation first
- **GIVEN** an application the platform reconciles itself
- **WHEN** a pin is performed
- **THEN** automated sync is suspended before the autoscaler is patched, and the
  undo descriptor records that it had been in force

#### Scenario: An application already not reconciling is left that way
- **GIVEN** an application whose automated sync a human had already suspended
- **WHEN** a pin is performed and later undone
- **THEN** the floor is put back and automated sync is left suspended

#### Scenario: The undo puts the floor back
- **GIVEN** a pin that was refuted or an incident that was withdrawn
- **WHEN** the undo runs
- **THEN** the floor recorded on the descriptor is set again

#### Scenario: A half-succeeding restore says which half
- **GIVEN** a pin whose undo can put the floor back and cannot restore
  reconciliation
- **WHEN** the undo runs
- **THEN** it reports both outcomes separately rather than raising

### Requirement: A pin mitigates without resolving
The system SHALL treat a confirmed pin as a mitigation and never as a resolution.
The repository still declares the autoscaler that flaps, the platform's
reconciliation is suspended so that nothing re-applies it, and the deployment is
now held at a size nobody chose for steady state. A withdrawal puts the first two
back, which returns the service to flapping.

The code tier SHALL be asked as it is for every other mode, and whatever it
answers SHALL be recorded as the answer it is. Unlike a shortfall of capacity,
this mode's fault genuinely is in a file - the autoscaler's scaling behaviour is
declared in the repository and a correct patch to it exists. The system SHALL NOT
require the agent to find it: an agent aimed by a conclusion reads what is in
front of it, and a rule about which file a model must reach fails on the reading
rather than on the behaviour it meant to constrain.

What the system SHALL NOT do is treat a patch as the resolution. The incident is
mitigated by the count stopping or it is not mitigated at all.

#### Scenario: The incident is reported as mitigated
- **GIVEN** a pin whose subsequent minutes show the service well
- **WHEN** the outcome is recorded
- **THEN** the hypothesis is confirmed, the incident is mitigated, and it is not
  reported as resolved

#### Scenario: Withdrawing returns the deployment to where it was found
- **GIVEN** a mitigated incident that a human then withdraws
- **WHEN** the undo runs
- **THEN** the floor and the reconciliation setting are both put back, and the
  count resumes moving

#### Scenario: A patch is not what ended the incident
- **GIVEN** an incident whose mode is autoscaling pathology and whose pin was
  confirmed
- **WHEN** the code tier is reached and answers, whether with a patch or with
  nothing to change
- **THEN** the answer is recorded as what it is, and the incident stays mitigated
  rather than resolved

### Requirement: The record says what a pin changed in the words of what it changed
The system SHALL narrate a pin and its withdrawal as what they are - a floor
raised, and a floor put back - and SHALL NOT describe either as a count being
set. Two actions in this estate now decide how many replicas a deployment runs,
and a record that called them both scaling would leave a reader unable to say
which one owns the number.

#### Scenario: A pin is said as a floor
- **WHEN** a performed pin is rendered for a reader
- **THEN** the line says the autoscaler's floor was raised, and names the
  application and both floors

#### Scenario: A withdrawal is said as a floor put back
- **WHEN** a pin's undo is rendered for a reader
- **THEN** the line says the floor was put back, and says whether automated sync
  was restored with it
