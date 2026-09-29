## ADDED Requirements

### Requirement: The read tier reports whether a deployment converged
The read tier SHALL offer a channel that answers, for one application, whether
the deployment it is running has finished arriving: the revision the platform is
converging on, how many replicas have reached it, how many have not, whether the
rolling update is paused, and when it entered that state - which is the moment
the deployment landed, said rather than counted from: a read tier has no clock,
and a duration is arithmetic the reader can do against an onset it already holds.

It exists because the five channels before it all read a deployment as an event
at an instant. The deploy history records that a sync happened; the diff records
what that sync carried; metrics, logs and the flag provider describe the service
and what was switched. A rollout is a stretch, and a stretch that has not ended
is invisible to every one of them - which is the whole of what this mode turns
on.

The channel SHALL answer for every application, not only for one mid-rollout. A
channel that said nothing about a converged deployment would be a channel a
reader consults only when they already suspect the answer.

#### Scenario: A rollout that has not finished is reported as such
- **GIVEN** an application whose replicas are split across two revisions
- **WHEN** the channel is read
- **THEN** it names both revisions, says how many replicas are on each, and says
  the rollout has not converged

#### Scenario: A converged deployment says so
- **GIVEN** an application every replica of which is on the deployed revision
- **WHEN** the channel is read
- **THEN** it says the deployment converged, and names the revision every replica
  is running

#### Scenario: A paused rollout says it is paused
- **GIVEN** an application whose rolling update was paused part way
- **WHEN** the channel is read
- **THEN** the answer says the rollout is paused, which is why it is not
  progressing

### Requirement: It reads the running deployment, not the revision history
The channel SHALL read the live Deployment resource through the platform's own
managed-resource endpoint - the same read the write tier makes to learn the
replica count it is about to replace - and SHALL NOT derive convergence from the
revision history.

The history is what the platform reports about syncs that completed. Whether the
pods have turned over is on the Deployment itself, and a field bolted onto a past
history entry would describe a sync that ended rather than one in progress, and
would be unavailable for any deployment not yet in the history.

The channel SHALL NOT introduce a new source. The application, the credential and
the route are the ones the deploy history already uses.

#### Scenario: The live resource is what is read
- **WHEN** the channel answers
- **THEN** the platform's managed-resource endpoint was called for the
  application's Deployment, and the revision history alone was not the basis of
  the answer

#### Scenario: An unreachable platform is not reported as a converged deployment
- **GIVEN** a platform that cannot be reached
- **WHEN** the channel is read
- **THEN** it fails as the other change channels fail, and never answers that the
  deployment converged

### Requirement: The channel reports the state and draws no conclusion
The channel SHALL report what the platform says and SHALL NOT label a rollout
healthy, stuck, wrong or dangerous. A rollout part way through is the ordinary
condition of every deployment for a minute or two, and a channel that called one
a fault would be deciding, on a timing it cannot know, something that belongs to
whoever weighs causes.

What it MAY say is when the state began, because that is a fact the platform
carries and is what separates a deployment turning over from one that stopped.

#### Scenario: A rollout in progress is not called a fault
- **GIVEN** an application mid-rollout
- **WHEN** the channel is read
- **THEN** the answer describes the split and when it began, and applies no
  verdict to it
