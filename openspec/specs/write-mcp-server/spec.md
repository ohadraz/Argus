# write-mcp-server Specification

## Purpose
The write tier: the single process that may change the state of the Target
Environment, and the typed client through which agents reach it. Its existence
apart from `argus-read-mcp` is what makes "read-only" a property of a running
process rather than a convention its callers are trusted to observe.
## Requirements
### Requirement: A write-tier MCP server runs as its own process
The system SHALL run `argus-write-mcp` as a process separate from
`argus-read-mcp`, exposing the tools that change state. The read server SHALL
contain no code path that mutates anything and SHALL hold no credential that
could authorize one, so that the autonomy tier is a property of which process is
running rather than a convention its callers observe.

#### Scenario: The write server is reachable alongside the read server
- **GIVEN** the stack is up
- **WHEN** each MCP server is asked to list its tools
- **THEN** both answer, and the tool that changes flag state is offered by the
  write server and not by the read server

#### Scenario: The read server holds no credential that can change state
- **GIVEN** the configuration each server is started with
- **WHEN** the read server's configuration is inspected
- **THEN** it carries no credential able to change flag state, only one able to
  evaluate

### Requirement: The write server can set a feature flag's state
The write server SHALL expose a tool that sets a named feature flag on or off in
the flag provider's configured environment, returning once the provider reports
the flag as evaluating to the requested state. The tool SHALL report a flag it
could not change as a failure rather than as success. One tool serves both
directions, because undoing a flag change and undoing that undo are the same
operation with the state reversed.

#### Scenario: An enabled flag is turned off
- **GIVEN** a flag that is enabled in the provider
- **WHEN** the tool is called to set that flag off
- **THEN** the flag is off afterwards, as the provider reports it

#### Scenario: A disabled flag is turned on
- **GIVEN** a flag that is disabled in the provider
- **WHEN** the tool is called to set that flag on
- **THEN** the flag is on afterwards, as the provider reports it

#### Scenario: The tool returns only once the change is visible
- **GIVEN** a flag whose state is about to be changed
- **WHEN** the tool returns successfully
- **THEN** an evaluation of that flag made immediately afterwards reports the
  requested state

#### Scenario: An unreachable provider is a failure
- **GIVEN** the flag provider cannot be reached
- **WHEN** the tool is called
- **THEN** it reports a failure, and does not report the flag as changed

### Requirement: The write server reports recent flag changes
The write server SHALL expose a tool reporting the flag changes the provider
recorded in the configured environment since a given moment - for each, the flag,
the state it was changed to, when, and who by - so that an agent can identify
which flag an incident is about and in which direction it moved.

This read SHALL live on the write server rather than the read server: the
provider issues no credential that can read its change history without also being
able to change a flag, and issuing the read server such a credential would defeat
the tier split.

#### Scenario: A flag that was switched on is reported as such
- **GIVEN** a flag was enabled in the environment after the given moment
- **WHEN** the flag-change tool is called
- **THEN** it reports that flag, changed to enabled

#### Scenario: A flag that was switched off is reported as such
- **GIVEN** a flag was disabled in the environment after the given moment
- **WHEN** the flag-change tool is called
- **THEN** it reports that flag, changed to disabled

#### Scenario: Changes before the window are not reported
- **GIVEN** a flag was changed before the given moment and none since
- **WHEN** the flag-change tool is called
- **THEN** that change is absent from the result

#### Scenario: An unreachable provider is a failure, not an empty history
- **GIVEN** the flag provider cannot be reached
- **WHEN** the flag-change tool is called
- **THEN** it reports a failure rather than reporting that nothing changed

### Requirement: The write server can restart a service
The write-tier server SHALL expose a tool that restarts a named service, shaped
like the deployment platform's own restart action - a resource action that
stamps a restart annotation on the workload's pod template, which is how Argo CD
and `kubectl rollout restart` both express it - rather than as an endpoint
invented here. The read-tier server SHALL hold no such tool and no credential
that could authorize one.

#### Scenario: A restart is available on the write tier alone
- **WHEN** the two servers' tool lists are read
- **THEN** the restart tool appears on the write server and not on the read
  server

#### Scenario: A restart names the service it acted on
- **WHEN** the restart tool is called for a service
- **THEN** it reports the service restarted and the instant the new process
  began, so the caller can confirm the restart landed rather than assume it

### Requirement: Each write tool is a typed function on a client package
The system SHALL expose every write tool as a typed function in a
`write_mcp_client` package installed into the agents that call it, rather than
requiring callers to name tools as strings and pass untyped payloads, so that a
mistyped tool name or argument is a static type error.

#### Scenario: A write tool is called through the typed client
- **GIVEN** the write server is running
- **WHEN** an agent calls the flag-revert function on `write_mcp_client`
- **THEN** the call succeeds and the flag is reverted

### Requirement: Every state-changing action carries an undo descriptor
The write tier SHALL return, with every action that changed persistent state, a
descriptor sufficient to put that state back - what was changed, and what it
held before. An action that changed no persistent state SHALL return no
descriptor, and SHALL say so explicitly rather than returning an empty one.

The descriptor is how a mitigation is unwound when its hypothesis is refuted or
its incident withdrawn. It is not what decides whether an action may be taken:
that is membership of the declared set of generic mitigations, and an action
with nothing to put back is admitted on the same terms as one with an undo.

#### Scenario: A flag change comes back with what it was
- **WHEN** a flag's state is set through the write tier
- **THEN** the result carries a descriptor naming the flag and the state it
  held before the call

#### Scenario: A restart comes back with nothing to put back
- **WHEN** a service is restarted through the write tier
- **THEN** the result carries no undo descriptor, and states that the action
  changed nothing that can be restored

### Requirement: A patch is written to a branch and never to the base
The system SHALL create a branch from the base branch's head and SHALL write
every file of a patch to that branch, naming the branch on each write. It SHALL
NOT write to the base branch. The credential it writes under SHALL reach the
Target Service's repository and no other (§15.1).

#### Scenario: A fix gets a branch cut from what is deployed
- **WHEN** a patch is written
- **THEN** the branch is created at the base branch's current head, so the fix
  applies to the code actually running

#### Scenario: Every write names the branch
- **WHEN** each file of a patch is written
- **THEN** the branch is named explicitly, so no write can fall back to the
  repository's default branch

#### Scenario: An existing file is replaced and a new file is created
- **GIVEN** a patch changing one file and adding another
- **WHEN** it is written
- **THEN** the change names the version it replaces, and the addition names none

### Requirement: A draft pull request is the furthest this tier goes
The system SHALL open pull requests as drafts and SHALL NOT expose any function
that merges one. Merging is a deploy and sits on the irreversible side of §13,
so the enforcement SHALL be that the function does not exist.

#### Scenario: The proposal carries the agent's own words
- **WHEN** a pull request is opened
- **THEN** its title and body are the ones the agent supplied, unaltered, and
  the body says which incident it answers

#### Scenario: A repository that refused is not reported as opened
- **WHEN** the repository refuses, is unreachable, or answers with no pull
  request in it
- **THEN** the call fails, so nothing downstream records a proposal that does
  not exist

### Requirement: Every file a patch names is written
The system SHALL write every path a patch names, tests included, and SHALL NOT
withhold any path from it. What bounds a change is the branch it lands on and
the human merge that would put it into service (§13) - not this tier's opinion
of which files an agent may touch.

#### Scenario: A patch that brings a test is written whole
- **GIVEN** a patch naming a source file and the test that exposes the bug
- **WHEN** it is written
- **THEN** both land on the branch, because the test is the half that shows the
  fix works

#### Scenario: Nothing in the repository is unwritable
- **WHEN** the tier's configuration and code are examined
- **THEN** there is no path it refuses and no setting that names one

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
