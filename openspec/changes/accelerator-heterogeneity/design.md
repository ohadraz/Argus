## Context

Two prerequisite changes have landed:
- `deployment-platform-port` gave Argus a port for the deployment platform,
  split by tier, with the Argo CD adapter the only code that knows a route.
- `mitigation-circumstances` gave every strategy one `Circumstances` value, so a
  new input is a field and not a parameter.

FM-33 needs both, and one more fact Argus has never read: where each replica runs.

What exists today:
- The adapter reads only `kind`, `name`, `namespace` and `createdAt` off the
  resource tree.
- The demo app's tree holds a single Pod, with no `info` and no `hosts`.
- The shop has no notion of a node, a GPU or a fraud check.

The design was settled with the user on 2026-10-07 (memory
`project_fm33_design`):
- **Story:** a fraud scorer.
- **The fault:** `ALLOW_TF32 = True`.
- **Where the GPU model is read:** Argo CD only, from the `Node` info item and
  the `hosts[].labels` entry `nvidia.com/gpu.product`.
- **Which GPU to pin to:** decided from the onset and the placement the
  Investigator recorded before any action.
- **Event:** the placement is published as one.
- **Lasting fix:** Code-Fix's choice.

## Goals / Non-Goals

**Goals:**
- Argus reads and records each replica's accelerator, and the timeline and the
  postmortem say it.
- `accelerator-heterogeneity` is a mode, answered by a pin to the accelerator the
  pre-onset replicas ran on, decided from the record and not from a read made
  when acting.
- The mode is staged end to end: scenario, e2e case, recording, graded fix and
  eval case.

**Non-Goals:**
- **A Kubernetes channel.** Argo CD is the only platform Argus reads. A cluster
  that exposes accelerators only through DRA, or one whose Argo CD does not
  allow-list the GPU label, yields no accelerator, and so no pin.
- **Pinning to several accelerators** through node affinity. Exactly one good
  accelerator or no action.
- **Asserting which lasting fix Code-Fix chooses.**
- **A paid eval run.** The eval case lands at `UNMEASURED`.

## Decisions

### D1. Placement is a port read returning Argus's values
`DeploymentPlatformReads.placements_of(application, /) -> list[PodPlacement]`.

`PodPlacement` lives in `argus_core.models` and holds:
- `pod: str`
- `node: str`
- `accelerator: str | None`
- `started_at: datetime`

It is a contract because the read tier, the Investigator, the events, the
orchestrator and Mitigation all name it, which is the `RolloutProgress`
precedent.

The adapter makes one `GET` of the resource tree:
- it takes the Pods' `info` item named `Node`, and their `createdAt`;
- it maps each node to the label `nvidia.com/gpu.product` from `hosts[]`, where
  each host has a `name` and `labels`.

Everything in that list is a named `Final` constant in `argocd.py`. A pod with
no `Node` item, or with an unparseable `createdAt`, is left out. A host with no
label gives `accelerator=None`.

*Alternative considered:* extend `newest_pod_started_at`. Rejected, because it
answers a different question and its callers want one moment.

### D2. Read tool `get_placements`
- `read_mcp_server/placements.py` holds the behaviour, registered as
  `@mcp.tool get_placements(service)`.
- `read_mcp_client.get_placements` returns `list[PodPlacement]`.
- A platform failure surfaces as a tool error, which the caller reports as
  unanswered.

### D3. The Investigator reads it as a fixed read, after the onset
`investigate()` gains a `fetch_placements: PlacementFetcher` seam.

After `OnsetDetected` and before the dispatcher is built, it reads the
placement once, the way it reads the metrics. On success it does three things:
- it publishes `PlacementRecorded(onset, pods)`;
- it records the read on the replay;
- it puts a placement paragraph into the opening message, naming each pod's
  node, accelerator and start time, and marking those that started at the onset
  under D6's rule.

On failure it publishes `RetrievalUnanswered` and carries `None`.

`Findings` gains `placement: RecordedPlacement | None = None`, where
`RecordedPlacement` holds `onset: datetime` and `pods: Sequence[PodPlacement]`.
The onset goes with the pods because the classification is meaningless without
the minute it was made against, and the walk's state carries no onset of its own.

*Alternative considered:* a model tool, as rollouts are. Rejected, because the
pin depends on the read, and a model that never asked would leave the strategy
nothing to decide from. A fixed read is also deterministic per incident, as the
metrics read is.

### D4. The orchestrator carries it
- `IncidentState.placement` is set from the findings by `investigator_node`, and
  the `StateDelta` carries it.
- `the_circumstances(alert, flag_changes, deployments, placement)` sets
  `Circumstances.placement: RecordedPlacement | None = None`.
- The three callers pass the state's or the findings' placement.
- Each round re-reads, as the flag history is re-read.

### D5. The mode
`FailureMode.ACCELERATOR_HETEROGENEITY = "accelerator-heterogeneity"` has a
maintainer comment, and its `meaning()` separates it from two modes:
- `output-quality-degradation`: here there is no revision at the onset;
- `bad-deployment`: here requests do not fail or slow.

The brief gains one paragraph saying how to read the placement: a pod that
started at the onset on an accelerator the others do not run on.

### D6. `PinToAcceleratorStrategy`
It maps from `ACCELERATOR_HETEROGENEITY` and classifies the pods of
`circumstances.placement` against its onset:
- **Onset-started:** `started_at >= onset - 1 minute`. The minute's grace exists
  because a measured onset is the first departed whole minute, while a
  reschedule lands inside a minute; a replica moved thirty seconds before the
  first minute that departed is the cause, not a bystander.
- **Pre-onset:** every other pod.

It returns `PinToAccelerator(application=service, accelerator=good)` only when
all of these hold:
- every pod has an accelerator;
- there is exactly one good accelerator;
- there is at least one suspect;
- no suspect is also good.

Otherwise it returns `None`, and the gate refuses with
`NO_MITIGATION_PROPOSED`. The walk then moves on to the next candidate, and
eventually to a human, which is how "overlap means escalate" is carried out
without a new route.

The onset rule itself lives on `RecordedPlacement`, as
`started_before_the_onset()` and `started_at_the_onset()`, because the
Investigator's opening message and the narration mark the same pods. The pin
decision built on it is a public function in its own module,
`agent_mitigation/accelerators.py`, so it can be tested as a unit.

### D7. The action, admission, perform and undo
**Model.** `PinToAccelerator(application, accelerator)` in
`argus_core.models.action`:
- `ActionType` is `pin_to_accelerator`;
- `_LEAVE_SOMETHING_TO_PUT_BACK` holds;
- the subject, and so the identity, is the application, as a pin of an
  autoscaler's is, so the cap counts pins of one deployment whatever card
  each named;
- the platform is `DEPLOYMENT_PLATFORM`;
- it joins `GENERIC_MITIGATIONS` as a drain.

**Port writes:**
- `accelerator_pin_of(application) -> str | None` reads the Deployment
  manifest's `spec.template.spec.nodeSelector` entry for the GPU label;
- `pin_to_accelerator(application, accelerator: str | None)` sends a `POST` to
  the resource route with `kind=Deployment`, `group=apps`, `version=v1` and
  `patchType=application/merge-patch+json`. The body is
  `{"spec":{"template":{"spec":{"nodeSelector":{LABEL: value}}}}}`, where `None`
  removes the key, as RFC 7386 does with null.

**Write server** (`write_mcp_server/accelerators.py`), following `pinning.py`:
1. Read the current pin. If it equals the one asked for, raise
   `an_exhausted_action`.
2. Read `is_syncing_itself`, and `suspend_sync` if it is on.
3. Build `AcceleratorPinUndo(application, was_pinned_to, pinned_to,
   was_syncing_itself)`.
4. Send the patch.

An unreachable platform carries `left_behind=undo` once sync has been
suspended.

The tool `restore_accelerator_pin` puts the selector back first and resumes sync
after, only where the undo says sync was on.

**Arrival** is `an_action_in_force_at_once`, the same as the floor.

**Client and agent:**
- client functions: `pin_to_accelerator` and `restore_accelerator_pin`;
- agent side: a `PerformingWrites` field, the `_perform` and
  `_what_it_would_have_done` cases, an `undoing.py` case and its `binding.py`
  entry.

### D8. The scorer and the scenario (demo app; code first, tests after)
**The scorer.** `src/io_shop/fraud_scoring.py`:
- `ALLOW_TF32 = True`;
- `TF32_ACCELERATORS = {"NVIDIA-A100-SXM4-40GB"}`;
- `score(features, accelerator)` is a fixed weighted sum. Where TF32 applies, its
  inputs are rounded to a 10-bit mantissa first;
- `held_for_review(price, accelerator)` derives its features from the price,
  with no random draw.

The weights and the threshold are chosen so that a measurable share of prices
flips on A100.

**The generator.**
- A frozen `Rescheduling` condition has `began_at`, `ended_at` and `earlier`. Its
  `share_of(minute)` is the same shape as `ModelUpgrade`'s.
- A fixed `1/replicas` of each minute's purchases is scored by the moved
  replica, assigned by purchase index with no new draw.
- `fraud_held_for_review_ratio` appears on `GeneratedMinute`, `MetricBucket` and
  `_the_buckets`, and as an exposition gauge.
- `QUERIES` gains `avg(fraud_held_for_review_ratio)`.

**The rule.** `io-shop-fraud-holds-high` (`FraudHoldsHigh`): reduce `mean` over
2 minutes, `gt` a threshold above the calm share, pending 5 minutes. The range
is two minutes for FM-17's reason, the three clean minutes after the window
freezes. It appears in `SERIES_RULES` and `_WHAT_FIRED`.

**The tree.**
- `ArgoCdResourceNode` gains `info: list[{name, value}]`, and
  `ArgoCdResourceTree` gains `hosts: list[{name, labels}]`.
- There is one pod per current replica, named `{app}-{suffix}-{i}`, on node
  `gpu-v100-{i}` labelled `Tesla-V100-SXM2-16GB`.
- While the scenario is running, one pod is on `gpu-a100-0`, labelled
  `NVIDIA-A100-SXM4-40GB`, with `createdAt` set to the onset.
- These are GPU Feature Discovery's real product spellings.

**The patch and the manifest.**
- `POST /argocd/{app}/resource` also accepts `kind=Deployment` with a merge
  patch that reaches only `spec.template.spec.nodeSelector`, and only the GPU
  label.
- The Deployment manifest shows the selector.
- A pin to V100 sets `ended_at` and re-places every pod on V100 with
  `createdAt` set to the pin.
- Removing the pin changes no placement.
- `reset()` clears the pin.

**The scenario.** `scorer-replica-rescheduled`:
- family "AI-specific", no deploy, onset backdated by
  `onset_backdate_minutes`, no flag;
- `seed`, `phase` and `generated_window` branches;
- a log line at the onset naming the pod rescheduled onto the A100 node;
- a console entry and a console column, "held for review".

**The fault** is on `main`, and `tests/io_shop/test_fraud_scoring.py` covers V100
and `ALLOW_TF32` paths that do not reach it.

### D9. What changes for every other incident
- The tree now carries three pods with `info` for every scenario, and every
  incident's opening message gains a placement paragraph.
- `newest_pod_started_at` still takes the newest pod, so restart arrival is
  unchanged.
- The prompt changes, so eval pools reset, and every bar is already stale.
- Replay recordings still replay, because the double serves in order.
- The full free `e2e_replay(mode='both')` is the check.

### D10. End to end
`tests/e2e/test_a_rescheduled_scorer_is_pinned_back.py` posts the Grafana payload
naming the staged rule, and asserts only relations Argus holds:
- the cause is `accelerator-heterogeneity`;
- a `PlacementRecorded` event precedes the first action;
- the last action is a pin whose accelerator is the one the recorded pre-onset
  pods ran on, and the rule confirmed it;
- the incident ends `mitigated`;
- a fix was proposed.

Around it:
- the case runs in `both` only;
- it gets a `record_incident.py` entry and an entry in
  `THE_RECORDINGS_THAT_MUST_CARRY_A_FIX`;
- a free rehearsal is borrowed from `both-categoriser-model-upgraded`, with the
  mode and the action rewritten;
- the paid `record(mode='both')` is asked for once everything free is green.

The eval case is `accelerator-heterogeneity-is-told-from-output-quality-degradation`,
at `UNMEASURED`. The Prometheus contract gains the new query.

## Risks / Trade-offs

- **The prompt grows on every incident** → a paragraph per walk, and an eval pool
  reset. Accepted: the placement is the only evidence for this mode, and a tool
  the model may skip would leave the strategy nothing.
- **The one-minute grace** → a pod restarted for an unrelated reason just before
  the onset on a good accelerator becomes a suspect that is also good. The answer
  is no action, which is the safe side.
- **Only one good accelerator is pinned to** → a fleet mixing two good kinds gets
  no pin. Accepted over node affinity, which would be a second write shape for an
  unstaged case.
- **Real Argo CD hides node labels unless they are allow-listed** →
  `accelerator=None`, so no pin. That is stated as a Non-Goal, and the spec
  says so.
- **The paid recording** → one `both` walk, at about $5 by the last record walk's
  rate, asked for explicitly.

## Migration Plan

There is no schema change. `RecordedPlacement` travels in events and state as
JSON, and every new field is optional. Deploy order is free: a read server
without the tool yields `None` in the Investigator, and a write server without
the pin tool is a tool error, which escalates as any other does.

## Open Questions

None. The user settled the story, the fault, the channel, the decision rule, the
event and the fix. The rest is decided above.
