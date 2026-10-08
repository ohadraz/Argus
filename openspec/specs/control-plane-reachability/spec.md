# control-plane-reachability Specification

## Purpose
What Argus does when the platform it mitigates *through* is the thing that is
broken. Five of the seven generic mitigations reach the estate through the
deployment platform, and the flag revert and the discard go elsewhere, so a failure of a
platform takes several actions away at once without being anybody's diagnosis.
This capability holds how that is told apart from an action that failed, which
platform each kind of action acts through, which candidates an unreachable
platform removes and which it leaves to be tried, and what the incident's record
says about it.

## Requirements

### Requirement: A platform that cannot be reached is reported as such

The write tier SHALL report a failure to reach the platform an action acts
through as an unreachable platform, distinguishably from an action that was
attempted and failed. A platform that does not answer, answers too late, or
answers that its own API is unavailable SHALL all be reported this way.

The distinction is the whole of it. An action that failed is about the action:
somebody reads it and asks what was wrong with this rollback. An unreachable
platform is about everything that goes through it, and a reader who is told the
first when the second is true will look in the wrong place.

Stated as a rule about reachability rather than about a particular vendor,
because the read that matters - "can I still act through this?" - is the same
read whatever the platform is.

#### Scenario: The platform does not answer
- **GIVEN** an action whose platform cannot be connected to
- **WHEN** the action is performed
- **THEN** the tier reports an unreachable platform, naming the platform

#### Scenario: The platform reports its own API unavailable
- **GIVEN** an action whose platform answers `503`
- **WHEN** the action is performed
- **THEN** the tier reports an unreachable platform, not a failed action

#### Scenario: An action that failed on its own terms is not reported as unreachability
- **GIVEN** a platform that answers, and rejects the action it was asked for
- **WHEN** the action is performed
- **THEN** the tier reports a failed action, and the platform is not said to be
  unreachable

### Requirement: Every action kind names the platform it acts through

The system SHALL record, for each kind of generic mitigation, which platform it
reaches the estate through. The restart, the deployment rollback, the scale-out
and the autoscaler pin SHALL name the deployment platform; the feature flag
revert SHALL name the flag provider.

Held as a property of the kind rather than derived at the point of failure. The
question is asked of candidates that have not been attempted, so it cannot be
answered by watching one fail.

#### Scenario: The five platform actions share a platform
- **WHEN** the platform of the restart, the rollback, the scale-out, the
  autoscaler pin and the pin to a card is asked for
- **THEN** all five name the same platform

#### Scenario: The flag revert names a different platform
- **WHEN** the platform of the feature flag revert is asked for
- **THEN** it names the flag provider, and not the deployment platform

### Requirement: An unreachable platform removes only the candidates that go through it

When an action reports an unreachable platform, the walk SHALL pass over every
remaining candidate whose action would act through that platform, and SHALL try
the remaining candidates as it otherwise would.

A platform failure is not Argus running out of moves. It removes the actions
that go through it, and an incident whose next candidate acts through a platform
that is still answering is one Argus can still mitigate. Retrying the actions
that share the failed platform buys nothing and costs a verification window
each.

#### Scenario: The walk falls through to a candidate on a reachable platform
- **GIVEN** an incident with a deployment rollback ranked above a flag revert,
  and a deployment platform that is unreachable
- **WHEN** the rollback is attempted and reports an unreachable platform
- **THEN** no further action through that platform is attempted, and the flag
  revert is proposed and taken

#### Scenario: Candidates sharing the failed platform are not attempted
- **GIVEN** an incident whose remaining candidates all act through the
  unreachable platform
- **WHEN** the first of them reports an unreachable platform
- **THEN** none of the others is attempted

### Requirement: The record says the platform was unreachable, once

The system SHALL publish one event per incident recording that a platform was
unreachable, naming the platform and the action kinds it took away. It SHALL NOT
publish one per candidate passed over.

Without it, an incident mitigated by the one action on a reachable platform
reads as though Argus preferred that action - which is a record that misstates
the reasoning it exists to hold. One event rather than one per candidate,
because the fact is about the platform and repeating it per candidate teaches a
reader to skim it.

#### Scenario: One event names the platform and what it took away
- **GIVEN** an incident in which three candidates are passed over for an
  unreachable platform
- **WHEN** the incident's events are read
- **THEN** exactly one of them records the platform as unreachable, and it names
  the action kinds that platform carries

### Requirement: An escalation over an unreachable platform names the platform

The incident SHALL escalate where an unreachable platform leaves no candidate on
a reachable platform, and what the escalation says SHALL name the platform and
the actions it took away rather than the transport failure of the one action that
was attempted.

#### Scenario: Nothing reachable remains
- **GIVEN** an incident whose every candidate acts through the unreachable
  platform
- **WHEN** the walk ends
- **THEN** the incident is escalated, and what it reports names the platform as
  unreachable and the action kinds that are unavailable

#### Scenario: A transport error is not what a person is handed
- **GIVEN** an escalation over an unreachable platform
- **WHEN** what it reports is read
- **THEN** it does not consist of the underlying transport error of a single
  action
