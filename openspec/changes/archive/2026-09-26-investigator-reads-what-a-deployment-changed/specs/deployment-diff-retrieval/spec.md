# deployment-diff-retrieval Specification

## Purpose

What one deployment changed, read as evidence. The fifth retrieval channel, and
the only one that answers about a change rather than about the service: given a
revision the change channel has already offered, it says which files differ
between that revision and the one deployed before it, and what changed in each.

It exists because two causes in Argus's vocabulary arrive identically and are
fixed differently. A bad deployment and a broken configuration both land as a
deployment, both move the same signals, and both are mitigated by returning the
deployment - but one leaves somebody a values file to fix and the other leaves
them the source. Nothing else Argus retrieves distinguishes them. Not the deploy
summary, whose source path names where a deployment's manifests live and is the
same directory whatever the commit touched; not the logs, which report a symptom;
not the metrics, which report its shape.

Keyed to a revision rather than to a window, because a deployment changed exactly
what it changed. There is nothing to widen, and so nothing for a model to name
beyond the revision it is asking about.

## ADDED Requirements

### Requirement: What a deployment changed is retrievable by naming its revision

The system SHALL offer, on the read-only tier, a tool that answers what one
deployment of a named service changed, taking the deployment's revision as its
only subject. The revision SHALL be the same reference the change channel reports
for that deployment, so that the two channels compose without the caller
translating between them.

The caller SHALL NOT be required to name the revision deployed before it. That
revision is in the deployment history and not in anything the caller has seen, so
a caller supplying it would be supplying a guess - and a comparison against a
guessed base is a description of the wrong change that reads exactly like a
description of the right one.

#### Scenario: A deployment's changed files are returned for its revision alone
- **GIVEN** a deployment history in which a named revision was preceded by
  another
- **WHEN** what that revision's deployment changed is requested, naming only the
  service and that revision
- **THEN** the files that differ between the preceding revision and the named one
  are returned

#### Scenario: The revision the change channel reported is the one that is accepted
- **GIVEN** a change event reporting a deployment
- **WHEN** that event's own reference is passed to this channel
- **THEN** it identifies the deployment, with no other reference required

### Requirement: The base of the comparison is the revision deployed before

The system SHALL take as the base of the comparison the revision the deployment
history records as deployed immediately before the named one, not the named
commit's parent in the repository.

A deployment is a change between two deployed states, and several commits can land
between two synchronisations. The commit's parent would then describe a fraction
of what the deployment shipped, while looking like the whole of it.

#### Scenario: Several commits between two deployments are all reported
- **GIVEN** a deployment whose revision is several commits ahead of the revision
  deployed before it
- **WHEN** what it changed is requested
- **THEN** every file that differs across all of those commits is reported

#### Scenario: A deployment with nothing before it says so
- **GIVEN** a revision that is the earliest in the deployment history
- **WHEN** what it changed is requested
- **THEN** the answer states that there is no earlier deployment to compare it
  against, and it is not reported as a deployment that changed nothing

### Requirement: The answer carries what changed in each file, not only which files

The system SHALL return, for each differing file, both its path and the change
made to it, as the difference itself rather than as a classification of it.

A path alone leaves the caller inferring configuration from a directory name,
which is the inference that fails: the difference between a port that moved and a
function that was rewritten is legible in the change and is guesswork in the path.

The system SHALL NOT label a path as code or as configuration. Which directories
hold configuration belongs to the repository being read and differs between
repositories, so a label applied here would be this system deciding something it
cannot know.

#### Scenario: A configuration change is shown as the value that moved
- **GIVEN** a deployment whose only change is one value in a configuration file
- **WHEN** what it changed is requested
- **THEN** the answer names that file and shows the value before and after it
  changed

#### Scenario: A code change is shown as the source that changed
- **GIVEN** a deployment that changed a source file
- **WHEN** what it changed is requested
- **THEN** the answer names that file and shows the lines that changed in it

#### Scenario: No path is labelled as code or as configuration
- **GIVEN** any deployment
- **WHEN** what it changed is requested
- **THEN** no path in the answer is described as being code or configuration

### Requirement: The answer is bounded, and says where it was bounded

The system SHALL bound both how many files one answer describes and how much of
each file's change it carries, and SHALL state in the answer whatever was left
out.

One deployment can be a formatting sweep across a repository. An answer returned
whole would spend a caller's entire remaining context on a change nobody needed
in full - and an answer silently shortened would be read as the whole change,
which is how a cause gets attributed to the last file that happened to fit.

#### Scenario: A change too large to carry whole reports what was omitted
- **GIVEN** a deployment whose change exceeds the configured bound
- **WHEN** what it changed is requested
- **THEN** the answer carries as much as the bound allows and states that it is
  incomplete, naming what was left out

#### Scenario: A change within the bound is reported without a notice
- **GIVEN** a deployment changing one small file
- **WHEN** what it changed is requested
- **THEN** the whole change is returned and nothing is said about omission

### Requirement: The answer is not narrowed to the service's own source

The system SHALL report every path a deployment changed, and SHALL NOT narrow the
answer to the directories configured as holding the service's own source.

That scope exists so that an agent reading a repository reads the service rather
than the rig that stages faults against it, and it is right for the channels that
search and read source. It is wrong here, and inverting: the configuration a
deployment ships lives outside the source tree by definition, so a scoped answer
would hide exactly the file that distinguishes a configuration change - and would
hide it as an empty comparison, which reads as a deployment that changed nothing.

#### Scenario: A configuration file outside the source scope is still reported
- **GIVEN** a deployment whose only change is to a file outside the directories
  configured as the service's own source
- **WHEN** what it changed is requested
- **THEN** that file is reported, and the answer is not empty

### Requirement: A deployment that changed nothing is distinguishable from one that could not be read

The system SHALL report a deployment whose comparison found no differing file as
a deployment that changed nothing, and SHALL report a failure to make the
comparison as a failure, never as an empty answer.

"This deployment changed nothing" is a conclusion an investigation acts on - it
rules the deployment out as a cause. A repository that could not be reached, a
history that could not be read, or a comparison the source refused to complete
support no such conclusion, and must not arrive looking like one that does.

#### Scenario: An unreachable repository is reported as a channel that could not be read
- **GIVEN** a repository the read tier cannot reach
- **WHEN** what a deployment changed is requested
- **THEN** the answer says the comparison could not be made, and does not say
  that nothing changed

#### Scenario: A deployment of an identical revision reports that nothing changed
- **GIVEN** a deployment whose revision matches the revision deployed before it
- **WHEN** what it changed is requested
- **THEN** the answer says the deployment changed nothing

### Requirement: The channel answers only about deployments

The system SHALL answer this channel's question only for a change that is a
deployment, and SHALL say so plainly when asked about a change of another kind.

A feature flag's change has no revision and no repository behind it. Asked about
one, this channel has nothing to compare and the caller has confused two kinds of
change - a correction that is cheap to make and only if it is made.

#### Scenario: A flag toggle's reference is refused with a reason
- **GIVEN** a change event for a feature flag toggle
- **WHEN** its reference is passed to this channel
- **THEN** the answer states that only a deployment has a revision to compare,
  and names the channel that reports flag changes

### Requirement: The Investigator is offered the channel and nothing it does not need

The system SHALL include this channel in the tools the Investigator is offered,
and the offered tool SHALL remain read-only like every other one it holds.

The channel SHALL NOT record a windowed reading of the investigation. A reading
says which minutes are already in front of the model, and this channel reads no
minutes - one recorded for it would put a windowed retrieval in the record for a
question that has no window.

#### Scenario: The channel appears in the Investigator's offered tools
- **GIVEN** an investigation about to open its conversation
- **WHEN** the tool definitions given to the model are inspected
- **THEN** this channel is among them, and none of the tools offered can change a
  flag, a deployment, or a pull request

#### Scenario: Reading what a deployment changed records no window
- **GIVEN** an investigation that has read what a deployment changed
- **WHEN** what that investigation has read is inspected
- **THEN** no reading with a window is recorded for this channel
