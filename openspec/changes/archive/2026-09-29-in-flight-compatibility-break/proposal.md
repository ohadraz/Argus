## Why

FM-35 in-flight compatibility break is the other half of tail/outlier's 3%, and
it is next by elimination rather than by share: with capacity covered entire it
is the only remaining half of a family that has a built half, and a family
half-covered is where a distinction is cheapest to draw, because the neighbour
it has to be told apart from already exists.

It is also the first incident in the catalogue where **no revision is at fault**.
Every mode Argus holds today has something a reader can point at - a commit, a
value, a flag, a heap, a controller, somebody else's service. Here both sides of
the deploy are correct, each one passes its own tests, and what is wrong is that
the two of them are serving at the same time. So the answer to "which change
broke this" is *none of them*, and the answer to "what does somebody fix" is not
a file.

## What Changes

- `FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK` - an eighth mode, whose meaning
  says what separates it from `bad-deployment`: there a revision landed and the
  code it carried is wrong, here a revision landed and stopped half-way, and
  what fails is the requests that cross between the two versions now serving.
- **A sixth retrieval channel: whether a deployment actually converged.** The
  deploy history says a revision was deployed and says nothing about whether it
  finished arriving, which is exactly the fact this mode turns on. The channel
  answers from the same Argo CD application read the history already makes -
  which revision the platform is converging on, how many replicas are on each
  side, whether the rolling update is paused, and when that state began. No new
  source, a new projection.
- It is the one channel that could not be inferred from the five that exist.
  Metrics describe the service, logs describe what it said, the flag provider
  and the deploy history describe what changed, and the diff describes what a
  change carried - and every one of them reads a deployment as an event that
  happened at an instant. A rollout is a stretch, and a stretch that has not
  ended is invisible to all five.
- A `half-finished-rollout` scenario in the Target Service. A revision changes
  the shape of what the summary cache stores, is deployed, and the rolling
  update is **paused** half-way - a real and first-class thing to do to a
  Deployment, and the reason nothing converges on its own. Three replicas write
  the new shape, three replicas cannot read it, and an account page fails when a
  replica on the old side draws an entry a replica on the new side wrote.
- **The failing share peaks at half-rolled-out, and that arithmetic is the
  fingerprint.** It is the product of two shares - written by the new side, read
  by the old - so it is zero at both ends of a rollout and largest in the middle.
  About one request in five here, with the cache carrying its usual nine in ten.
  No other mode in the set produces a rate that a rollout *finishing* would take
  to zero.
- Both revisions are correct, and the fixture says so where it counts: each one
  alone leaves `tests/io_shop` green, so `grade_fixes` has nothing to grade and
  Code-Fix has no defect to find. What is left to fix is an expand-contract
  migration nobody performed, which is a process rather than a patch.
- **Rolling the deployment back is the mitigation**, and it is `bad-deployment`'s
  action for the third time - after that mode and `config-induced-failure`.
  Returning the deployment to the revision before it converges every replica
  onto one version, and one version reading and writing one shape is a shop that
  works whichever version it is.
- A restart is refuted, as it is for the two dependency modes: the process comes
  back, the fleet is still half and half, and nothing about the mixture is the
  process's doing.
- **The near-miss here is refuted in the record rather than by the estate, and
  that is stated rather than smoothed over.** A reader who calls this a bad
  deployment reaches the right action, so the incident ends either way. What the
  wrong reading costs is the account: a postmortem naming a revision that is not
  at fault, an action item to patch code that has no defect in it, and a team
  that ships the same commit again next week because nothing told them the
  rollout was the thing that went wrong. This is the mode that makes the
  taxonomy's own claim concrete - a mode is a distinction a reader makes, not
  one the dispatch table makes for them.
- Mitigated, never resolved, in the same form the other two rollback modes take.
  The repository still declares the new revision, reconciliation is suspended so
  nothing re-applies it, and a withdrawal returns the shop to a rollout stopped
  half-way.

## Capabilities

### New Capabilities

- `rollout-progress-retrieval`: whether the deployment the history's last entry
  records has converged, and what is serving while it has not - the projection,
  the tool that offers it, what it says about a deployment that finished
  normally, and why the channel exists beside a history that already names the
  revision.
- `in-flight-compatibility-scenario`: the Target Service staging a rollout
  stopped half-way - what its telemetry does, why the failing share peaks in the
  middle and is zero at both ends, what its live condition is, why a restart is
  refuted against it, and why both revisions pass their own tests.

### Modified Capabilities

- `investigator-cause-detection`: in-flight compatibility break is a determinable
  mode, and the requirement says what evidence separates it from a bad
  deployment - a rollout that has not finished, which is a fact about the
  deployment rather than about the code it carried.
- `deployment-rollback-mitigation`: a third mode maps to returning the
  deployment, and for a reason the first two do not share. There the revision
  carried the fault and going back removes it; here going back removes nothing
  and *converges* the fleet, which is what ends the incident - so the requirement
  states what the action actually restores, which is one version serving rather
  than a particular version serving.

The read tool is a requirement of the first new capability rather than a delta on
`read-mcp-server`, and the platform stand-in answering for a rollout in progress
is a requirement of the second rather than a delta on
`target-service-scenario-control` - which is where the rollback, the cache
scenario, the scale-out and the pin all put theirs.

## Impact

- `argus_core.models`: `FailureMode` an eighth value and its meaning. No action,
  no undo descriptor and no new tag in the action union - the mitigation is one
  that already exists, which is the whole of why this mode is cheaper than the
  seventh.
- `read_mcp_server`: a `rollouts.py` beside `deployments.py`, reading the same
  application payload `argocd.py` already fetches; a tool on the server and a
  typed function on `read_mcp_client`.
- `agent_mitigation`: `IN_FLIGHT_COMPATIBILITY_BREAK` mapped to the existing
  `RollbackDeploymentStrategy` in `DEFAULT_STRATEGIES`.
- `Argus-Demo-Target-App`: the scenario; a rollout in `ScenarioState` whose
  paused mixture the platform stand-in reports; a served page that fails when the
  two sides of it disagree; two real commits, the second of which changes the
  stored shape of a summary-cache entry and is the diff that is the diagnosis;
  the console entry, under a family of its own beside `the-tail`.
- Recordings: a new `both-half-finished-rollout` corpus, and every existing
  `both-*` corpus goes stale the moment the Investigator's tool list moves -
  which a sixth channel does, more than a mode's meaning did.
- Evals: an Investigator case for the new mode, and a case asserting
  `bad-deployment` is *not* diagnosed where the deploy landed and did not finish.
- `docs/failure-modes-backlog.md`: tail/outlier stops being "Partly" and becomes
  the third family covered entire, and the next thing becomes a member of
  foundational integrity - the largest family with nothing built in it.
