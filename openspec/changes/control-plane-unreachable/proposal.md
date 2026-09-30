## Why

Four of Argus's five declared mitigations - the restart, the rollback, the
scale-out and the autoscaler pin - reach the estate through one thing: Argo CD.
Only the flag revert goes elsewhere. So a failure of that platform is unlike
every failure Argus is built for: it does not take one action away, it takes
four away at once, and it takes them away without being anybody's diagnosis.

Today the walk handles it by accident. A rollback that cannot reach Argo CD
raises an `httpx` error, the broad `except` in `agent_mitigation.trying` turns it
into `Verdict.ESCALATED`, and the incident ends on the first failed candidate
with a transport error in its detail. Two things are wrong with that. The walk
learns nothing - it never discovers that the platform is the problem rather than
the action - and the person who picks the incident up is handed
`could not roll back deployment: ConnectError(...)`, which reads as one action
misbehaving.

What it should do instead is narrow itself to what is still reachable. The flag
provider is a different platform and is still answering, so an incident whose
next candidate is a flag revert is one Argus can still mitigate. That is the
difference between knowing the failure mode and having learnt one scenario.

## What Changes

- An unreachable control plane becomes a thing with a name, told apart from an
  action that failed. The write tier reports it distinguishably - over the same
  marker mechanism `ActionExhausted` already uses - and the mitigation agent
  catches it ahead of the broad `except`, as it already catches an exhausted
  action ahead of it and for the same reason.
- Each action kind learns which platform it reaches the estate through. An
  unreachable platform then removes exactly the candidates that go through it,
  and leaves the rest to be tried.
- The record says the platform was unreachable, once, rather than saying nothing
  or saying it per skipped candidate. Without it an incident mitigated by the
  flag revert reads as though Argus simply preferred the flag.
- Where nothing reachable remains, the escalation names the platform and the
  actions it took away, in place of a transport error.
- A new scenario stages it: a deployment and a flag both move in the window, the
  deployment ranks first, and the Target Environment's Argo CD routes that
  *change* something answer `503`. The routes that only report state keep
  answering, because a platform Argus cannot see is a different incident - one
  where the deployment goes unnoticed and no rollback is ever ranked. Argus
  reaches for the rollback, cannot, falls through to the flag revert, and the
  incident ends `MITIGATED`.

## Capabilities

### New Capabilities
- `control-plane-reachability`: what Argus does when the platform it mitigates
  *through* is the thing that is broken - how that is told apart from an action
  that failed, which candidates it removes, and what the record says about it.
- `control-plane-failure-scenario`: the staged incident. A cause with candidates
  on two platforms, one of which is down, so that falling through to the
  reachable one is what the walk has to do.

### Modified Capabilities
- `mitigation-retry-walk`: a candidate may now be passed over because the
  platform it would act through is unreachable, which is neither a refusal at
  the gate nor a refuted attempt.
- `write-mcp-server`: the four Argo CD-backed tools report an unreachable
  platform as such, rather than letting a transport error surface as a generic
  tool failure.
- `target-service-scenario-control`: a switch that makes the Target
  Environment's Argo CD routes answer as a platform whose API server is down.
- `incident-event-stream`: the new event, and the sentence it is narrated as.

## Impact

- `argus_core.mcp_transport` - the marker and the typed exception, beside
  `ActionExhausted`.
- `argus_core.models.action` - which platform each action kind reaches the
  estate through.
- `argus_core.events` and `argus_narration` - the event and its line.
- `write_mcp_server` - `rolling_back`, `restarting`, `scaling`, `pinning` raise
  it; the predicate that recognises it belongs with the rest of the platform's
  vocabulary in `argocd.py`.
- `agent_mitigation` - `trying.py` catches it; the candidate ordering passes
  over the platform's actions.
- `Argus-Demo-Target-App` - the scenario switch over the `/argocd/*` routes.
- `docs/spec-and-architecture.md` §13, and the failure-mode backlog's table.
- One recorded walk under `both`, for the e2e case to replay. Nothing here
  varies by which tool found a file, so the other two modes are not recorded.
