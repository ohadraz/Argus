## Why

FM-25 autoscaling pathology is the other half of capacity's 13%, and it is the
only family member whose blocker was a capability rather than an idea: nothing
could stage an autoscaler misbehaving until a replica count existed, was visible
in telemetry, and could be changed. Demand saturation built all three.

It is also the first incident in the catalogue where a **control loop** is the
fault. Every mode Argus holds today is a thing that was done once - a flag moved,
a revision shipped, a value changed, a heap filled, load arrived - and is
answered by doing something once. A flapping autoscaler is a thing that keeps
being done, which is why it is the one incident where scaling out is *refuted*:
the count Argus sets is put back within a minute by a controller that is still
running. That is a lesson the scale-out spec already reasons about for GitOps
sync and cannot demonstrate, because nothing in the fixture has ever put a
replica count back.

## What Changes

- `FailureMode.AUTOSCALING_PATHOLOGY` - a seventh mode, whose meaning says what
  separates it from `demand-saturation`: there the capacity is fixed and the load
  outgrew it, here the capacity itself is moving, minute by minute, with nothing
  deployed and nobody scaling.
- **Pinning the autoscaler is the fifth generic mitigation**, and the first that
  stops something rather than adding or restoring something. It raises the
  autoscaler's floor to its own ceiling - `minReplicas` up to `maxReplicas` -
  which halts the oscillation and leaves the deployment at the largest count
  somebody already declared for it, in one write.
- It is performed as a patch of the live `HorizontalPodAutoscaler` through Argo
  CD's `PatchResource`, not as a `scale` of the Deployment. **You cannot scale a
  deployment an autoscaler owns**: the controller re-derives the count from its
  own metric within a sync period, so a `scale` action against the Deployment is
  a write with a timer on it. Changing the controller is the only honest
  mechanism, and it is what makes this a distinct action rather than a fifth
  caller of `scale`.
- The action names the application and carries no count, for the reason a
  scale-out carries none - and for one more: the count is not Argus's to choose
  even in principle. `maxReplicas` is a bound a human declared for this
  deployment, read from the live resource, so pinning there asserts nothing new
  about the estate. It is still bounded by the tier's own ceiling, which is what
  keeps an autoscaler declared with `maxReplicas: 400` from being obeyed.
- Pinning at the ceiling and not at the count in force. The oscillation means the
  count in force is a coin toss - caught at the bottom of the cycle, pinning it
  would freeze the shop saturated and call that a mitigation.
- `AutoscalerUndo` records **two** things, as `ReplicaUndo` does and for the same
  two reasons: the floor the autoscaler had, and whether the platform was
  reconciling the application itself. Argo CD re-applies the HPA manifest from
  git at its next sync, so suspending automated sync is part of performing the
  pin rather than a separate concern, and the setting is never restored to a
  default.
- An `autoscaler-flapping` scenario in the Target Service. Traffic sits steady at
  two and a half times its baseline - more than three replicas can serve and
  less than six can - and the shop's autoscaler is declared with no
  stabilisation window, so it scales up on a saturated minute, reads the
  utilisation its own scaling just lowered, and scales back down the minute
  after. `cpu_limit_cores` alternates between three cores and six with an empty
  deploy history, no flag moved, memory flat and nobody having touched anything.
- **Every minute of it is elevated, and that is a constraint rather than a
  detail.** A trough that fell back to baseline would read as recovery under the
  rule Mitigation judges by - a stretch since an action with one clear minute and
  no two consecutive elevated ones is a confirmation - so any action at all would
  be accidentally confirmed on the next down-swing. The queue a saturated minute
  builds drains across the minute after it rather than vanishing at the boundary,
  which is both what a service never reaching steady state actually does and what
  keeps the wrong answer wrong.
- Two wrong answers are therefore refutable rather than accidentally right. A
  restart changes nothing, as it does not for saturation. A **scale-out** is the
  near-miss - the mode next door, reached by a reader who saw pinned utilisation
  and stopped - and the autoscaler puts its count back, so it is refuted by the
  fixture rather than by a rule.
- Mitigated, never resolved. The values file still declares the autoscaler that
  flaps, reconciliation is suspended so nothing re-applies it, and a withdrawal
  puts both back - which returns the shop to flapping.

## Capabilities

### New Capabilities

- `autoscaler-pinning-mitigation`: autoscaling pathology as a failure mode of its
  own, and raising an autoscaler's floor to its ceiling as the mitigation that
  answers it - why the deployment's own `scale` cannot serve, who resolves the
  count, the bound that still applies, the sync suspension it needs, and the
  two-part undo it leaves.
- `autoscaler-flapping-scenario`: the Target Service staging a control loop that
  oscillates - what its telemetry does, why no minute of it falls clear, what its
  live condition is, and why both a restart and a scale-out are refuted against
  it.

### Modified Capabilities

- `investigator-cause-detection`: autoscaling pathology is a determinable mode,
  and the requirement says what evidence separates it from demand saturation - a
  capacity that is itself moving.
- `scale-out-mitigation`: a scale-out against a deployment an autoscaler owns is
  a write the controller undoes, which the requirement about suspended
  reconciliation now states as the general rule it is - anything that re-derives
  a replica count has to be suspended or changed, and git is only one such thing.

The write tool is a requirement of the first new capability rather than a delta
on `write-mcp-server`, and the platform stand-in answering for a second kind of
live resource is a requirement of the second rather than a delta on
`target-service-scenario-control` - which is where the rollback, the cache
scenario and the scale-out all put theirs.

## Impact

- `argus_core.models`: `FailureMode` a seventh value and its meaning; `action.py`
  a `PinAutoscaler` action, a `PIN_AUTOSCALER` tag in the union and the
  `ActionType` literal, its membership of the kinds that leave something to put
  back, and the four `match`es over the union that stop compiling until they
  answer for it; `undo_descriptor.py` an `AutoscalerUndo` carrying the prior floor
  and the prior sync policy, and an `AutoscalingRestored` pair beside
  `CapacityRestored`.
- `write_mcp_server`: a `pinning.py` beside `scaling.py`, a tool on the server, a
  typed function on `write_mcp_client`, and a settings slice naming the patch
  route.
- `agent_mitigation`: a `PinAutoscalerStrategy`, its entry in
  `DEFAULT_STRATEGIES`, `PIN_AUTOSCALER` in the pre-authorised set, and a phrase
  for it in the sentence a walk says about what it is about to try.
- `argus_narration`: words for a fifth action kind and for its withdrawal.
- `Argus-Demo-Target-App`: the scenario; an autoscaler in `ScenarioState` whose
  floor the platform stand-in's patch route changes; a `Capacity` that derives
  each minute's count from the previous minute's utilisation rather than from a
  list of resizes; a queue that drains across minutes in the generator; the HPA
  stanza in `deploy/values-production.yaml`; and the console entry under the
  capacity family.
- Recordings: a new `both-autoscaler-flapping` corpus, and the thirteen existing
  `both-*` corpora go stale the moment the Investigator's tool schema moves -
  which the seventh mode's meaning does.
- Evals: an Investigator case for the new mode, and a case asserting demand
  saturation is *not* diagnosed where the capacity is the thing that moved.
- `docs/failure-modes-backlog.md`: the capacity row stops being "Partly" and
  becomes the second family fully covered, and FM-35 becomes the next thing.
