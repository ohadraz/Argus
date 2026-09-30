## ADDED Requirements

### Requirement: An unreachable platform is an event of its own

The system SHALL publish a typed event recording that a platform could not be
reached, carrying the platform and the kinds of action that platform carries, so
that a reader learns what was taken away rather than only that something was.

Self-describing on the same terms as every other event: the action kinds are
carried in the event rather than left to be looked up from the map that holds
them, because an incident read months later is read without the code that
published it, and a platform's name alone tells a reader nothing about what it
cost them.

#### Scenario: The event names the platform
- **GIVEN** an incident in which a platform was found unreachable
- **WHEN** its recorded events are read
- **THEN** one of them names that platform as unreachable

#### Scenario: The event names what the platform took away
- **GIVEN** such an event
- **WHEN** it is read
- **THEN** it carries the kinds of action that act through that platform,
  without reference to the code that published it

### Requirement: It is published where the walk learnt it

The event SHALL be published at the moment the walk learns the platform is
unreachable - after the attempt that discovered it, and before the candidate
that follows - and by the walk rather than by the tier whose call failed.

The stream is read as a story in the order it happened, and an event explaining
why later candidates went untried is only an explanation if it stands before
them. Published by the walk because the walk is what learnt it: the tier
reported a failed call, which is not yet the fact that a platform is
unavailable to this incident, and a tier that published against an incident
would be publishing about work it cannot see the shape of.

#### Scenario: It stands between the attempt and the fall-through
- **GIVEN** an incident in which an attempt failed on an unreachable platform
  and a later candidate was acted on
- **WHEN** the recorded events are read in order
- **THEN** the platform's event follows the failed attempt and precedes the
  events of the candidate that was acted on

#### Scenario: The tier publishes nothing
- **GIVEN** a write-tier call that failed because its platform was unreachable
- **WHEN** the events published by that call are examined
- **THEN** it published none, and the event came from the walk

### Requirement: It is said as one line naming the platform and what it took away

The event SHALL be narrated as a single line naming the platform and the actions
it made unavailable, in the same words wherever the incident is told.

An incident mitigated by the one action on a reachable platform reads, without
this line, as though Argus simply preferred that action - which is the record
misstating the reasoning it exists to hold. One line rather than a line per
candidate, because the fact is about the platform: repeated per candidate it
teaches a reader to skim exactly the sentence that explains the outcome.

#### Scenario: What is said names the platform and the actions
- **GIVEN** a recorded unreachable platform
- **WHEN** the event is narrated
- **THEN** the line says that platform could not be reached and which actions
  were unavailable while it could not

#### Scenario: Every destination says it the same way
- **GIVEN** an incident whose platform was unreachable
- **WHEN** the incident is told on the dashboard, in Slack and in its postmortem
- **THEN** the line is the same in each
