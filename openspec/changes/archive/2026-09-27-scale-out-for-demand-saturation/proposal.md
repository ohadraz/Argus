## Why

FM-13 resource exhaustion is 13% of real incidents and Argus handles half of it.
The leak half - consumption climbing while traffic does not - is built, diagnosed
as `resource-leak` and answered with a restart. The other half is a resource that
was sized correctly for load that has since grown, and it is the half the
taxonomy singles out as the one a system without the distinction gets wrong: it
looks like a leak on a latency graph, and a restart makes it briefly better
before it returns. Argus today has no signal that separates them, no mode that
names the difference, and no action that answers it - every mitigation it owns
puts something back, and this is the one that has to add something.

It is also the floor FM-25 autoscaling pathology stands on. Nothing can stage an
autoscaler misbehaving until a replica count is a thing that exists, is visible
in telemetry, and can be changed.

## What Changes

- A metric bucket carries the CPU the service was using and the capacity it is
  measured against, as `cpu_used_cores` and `cpu_limit_cores` - the pair, for the
  reason memory is a pair. Capacity is the deployment's total, so scaling out
  moves it.
- CPU is a **diagnostic** series, not a departure signal. The detector goes on
  dating an onset from the error rate, the median, the 95th, the 99th and the
  heap. Utilisation tracks traffic and traffic has a daily shape, so a busy hour
  is not an incident - and the incident here is the latency the saturation
  caused, which the existing five already see.
- `FailureMode.DEMAND_SATURATION` - a sixth mode, with what separates it from
  `resource-leak` (the consumption moved *with* the traffic) and from
  `bad-deployment` and `internal-dependency-failure` (nothing changed, and the
  time is spent in the service's own work) travelling into the tool schema beside
  it.
- **Scaling out is the fourth generic mitigation**, and the first that adds
  capacity rather than restoring state. It runs Argo CD's own built-in `scale`
  resource action against the application's Deployment, through the same
  `resource/actions/v2` endpoint the restart already uses, with a `replicas`
  parameter.
- The action names the application and not a number. The count it replaces is
  live state that only the write tier can read, so the tier resolves the target -
  doubling what is running, bounded by a ceiling it is configured with - and
  reports back which counts those were, exactly as a rollback reports which
  history entry it returned to.
- Its undo descriptor records **two** things, like the rollback's: the replica
  count that was running, and whether the platform was reconciling the
  application itself. Argo CD reverts a live `spec.replicas` on its next sync
  back to the `replicas: 3` in git, so suspending automated sync is part of
  performing the scale rather than a separate concern.
- A `cpu-saturation` scenario in the Target Service: reported volume ramps well
  past what three replicas were sized for, CPU reaches its ceiling, the median,
  the 95th and the 99th climb together, memory stays flat, no flag moved and
  nothing was deployed. Generated rather than authored, so the telemetry reacts:
  CPU pressure is computed from the live replica count, which means scaling out
  ends the incident and **restarting it does not** - the wrong answer is
  refutable rather than accidentally right, which is what makes the split worth
  having.
- Mitigated, never resolved. Git still says three replicas, the platform's
  reconciliation is suspended so that nothing re-applies it, the traffic is still
  elevated, and both of the first two are what a withdrawal puts back. There is
  no code fix: the shop's source is correct, and capacity is not a defect to
  patch - so this is the second mode out of Code-Fix's reach, after
  `internal-dependency-failure`.

## Capabilities

### New Capabilities

- `scale-out-mitigation`: demand saturation as a failure mode of its own, and
  raising a deployment's replica count as the mitigation that answers it - what
  the action carries, who resolves the target count, the ceiling that bounds it,
  the sync suspension it needs, and the two-part undo it leaves.
- `demand-saturation-scenario`: the Target Service staging load beyond the
  capacity it was sized for - what its telemetry does, which series carry it,
  what its live condition is, and why a restart is refuted against it.

### Modified Capabilities

- `resource-metrics`: a bucket carries CPU used against CPU capacity, with the
  aggregation rule each gauge needs and a nullable capacity for the deployment
  that imposes no limit.
- `trend-onset-detection`: CPU is retrieved and not judged - the series an onset
  is dated from stay the five they are, and the reason is stated rather than
  left as an omission.
- `investigator-cause-detection`: demand saturation is a determinable mode, and
  the requirement says what evidence separates it from a leak.
- `generic-mitigation-tier`: a mitigation with a magnitude is bounded by a ceiling
  as well as by the cap that bounds how often it may be attempted.

The write tool and the scenario's live condition are requirements of the two new
capabilities rather than deltas on `write-mcp-server` and
`target-service-scenario-control`, which is where the rollback and the cache
scenario put theirs.

## Impact

- `argus_core.models`: `MetricBucket` gains two fields; `FailureMode` a sixth
  value and its meaning; `action.py` a `ScaleOut` action, a `SCALE_OUT` tag in
  the union, the `ActionType` literal, the set of kinds that leave something to
  put back, and the four `match`es over the union that stop compiling until they
  answer for it; `undo_descriptor.py` a `ReplicaUndo` carrying the prior count
  and the prior sync policy.
- `write_mcp_server`: a `scaling.py` beside `restarting.py` and `rolling_back.py`,
  a tool on the server, and a typed function on `write_mcp_client`.
- `agent_mitigation`: a `ScaleOutStrategy`, its entry in `DEFAULT_STRATEGIES`,
  and `SCALE_OUT` in the pre-authorised set.
- `argus_narration`: words for a fourth action kind and for its withdrawal.
- `Argus-Demo-Target-App`: the scenario, a replica count in `ScenarioState` that
  the `argocd` stand-in's `scale` action changes, CPU in the generator computed
  from reported volume against that count, and the new pair on the metrics
  endpoint.
- Recordings: a new `both-cpu-saturation` corpus, and the twelve existing `both-*`
  corpora go stale the moment the Investigator's brief or tool schema moves -
  which the sixth mode's meaning does.
- Evals: an Investigator case for the new mode, and a case asserting a leak is
  not diagnosed where the traffic moved with the consumption.
- `docs/failure-modes-backlog.md`: the capacity row stops being "Partly", and
  FM-25 becomes the next thing to build rather than the one blocked behind this.
