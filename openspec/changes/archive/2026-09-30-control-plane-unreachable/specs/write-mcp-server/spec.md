## ADDED Requirements

### Requirement: A platform that could not be reached is reported apart from an action that failed

The write tier SHALL report a failure to reach the deployment platform as an
unreachable platform, naming it, rather than as a failure of the action asked
for. The four tools that act through that platform - the deployment rollback,
the service restart, the scale-out and the autoscaler pin - SHALL each report it
this way. A platform that refuses the connection, does not answer within the
request timeout, or answers that its own API is unavailable SHALL all be
reported this way.

The tier is the only place that holds both facts at once - which action was
asked for, and whether anything was there to receive it. Above it there is an
exception and a message, and a caller made to tell "the rollback was rejected"
from "nothing was there to reject it" by reading the words of a refusal would be
parsing prose for something the tier knew and threw away.

#### Scenario: A platform that does not answer
- **GIVEN** a deployment platform that cannot be connected to
- **WHEN** any of the rollback, the restart, the scale-out or the pin is called
- **THEN** each reports an unreachable platform, naming the platform

#### Scenario: A platform that reports its own API unavailable
- **GIVEN** a deployment platform answering that its API is unavailable
- **WHEN** one of the four tools is called
- **THEN** it reports an unreachable platform and not a failed action

#### Scenario: An action the platform answered and rejected is not unreachability
- **GIVEN** a deployment platform that answers, and rejects the action asked for
- **WHEN** the tool is called
- **THEN** it reports a failed action, and does not report the platform as
  unreachable

### Requirement: It travels over the marker an exhausted action already travels over

The tier SHALL carry the distinction to its callers by the mechanism that
already carries an exhausted action: a marker in what the failing tool reports,
recognised where a tool's reported error becomes an exception, and raised there
as a typed exception of its own. That exception SHALL be a kind of the tier's
general tool failure, so that a caller which does not know about it catches it
as it always did. The recognition SHALL happen in that one place and SHALL NOT
be repeated in the tier's typed client or in a calling agent.

The protocol gives a tool one way to fail, so a second kind of failure is told
from the first by what the failure says rather than by a channel of its own -
which is the problem an exhausted action already solved, and solving it twice
differently would leave two conventions for one shape of fact. Drawn where the
error becomes an exception because any distinction drawn later is a second
reading of the same field, and two readings drift.

#### Scenario: A caller gets a typed exception rather than a message to parse
- **GIVEN** a tool call that failed because its platform could not be reached
- **WHEN** the call is made through the typed client
- **THEN** the caller can tell an unreachable platform from a failed action
  without reading the text of the failure

#### Scenario: A caller that does not know about it is unaffected
- **GIVEN** a caller that handles the tier's general tool failure and nothing
  more
- **WHEN** a tool reports an unreachable platform
- **THEN** that caller catches it as it catches any other tool failure

#### Scenario: The distinction is drawn in one place
- **WHEN** the code that turns a reported tool error into an exception is read
- **THEN** the unreachable platform is recognised there, and nowhere downstream
  of it

### Requirement: An unreachable platform is not an unreachable write server

The system SHALL keep the platform an action acts through distinct from the
write server itself. A write server that cannot be reached at all SHALL NOT be
reported as an unreachable platform, and a reachable write server whose platform
is down SHALL NOT be reported as the server being unreachable.

The two look alike and mean opposite things. If the write server is gone, every
action is unavailable whatever platform it acts through and there is nothing
left to narrow to; if a platform is down, the actions on the other platform are
still there to be tried. A walk that narrows itself by platform has to know
which of the two it is looking at.

#### Scenario: The write server itself is unreachable
- **GIVEN** a write server that no session can be had with
- **WHEN** an action is attempted
- **THEN** what is reported is the server being unreachable, and no platform is
  named as unreachable

#### Scenario: The server answers and the platform does not
- **GIVEN** a write server that answers and a deployment platform that does not
- **WHEN** an action through that platform is attempted
- **THEN** what is reported is the platform being unreachable, and not the
  server

### Requirement: Recognising the platform's answer is vocabulary; raising is the action's own

The platform's vocabulary SHALL hold the predicate that recognises a response as
the platform reporting its own API unavailable, shared by every tool that speaks
to it. Each tool SHALL raise for itself, and no shared helper SHALL raise on a
tool's behalf.

Which status and which shape of body mean "this platform is not answering for
itself" is a fact about the platform, and a second copy of it is a second copy
that comes to disagree with the first. What the caller should then be told is
not a fact about the platform at all: it is the action's own business, and each
module's name for its failure is what that module's callers catch.

#### Scenario: The four tools recognise the same answer the same way
- **GIVEN** a response in which the platform reports its own API unavailable
- **WHEN** each of the four tools receives it
- **THEN** all four recognise it, by the one predicate that holds the platform's
  vocabulary

#### Scenario: The vocabulary raises nothing
- **WHEN** the module holding the platform's vocabulary is read
- **THEN** it decides what a response means and raises no exception of its own
