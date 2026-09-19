## ADDED Requirements

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

## MODIFIED Requirements

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
