## Why

FM-33, accelerator heterogeneity, is the last failure mode in the backlog that is
neither built nor out of scope. A replica is rescheduled onto a different kind of
GPU with no deployment behind it, and the model it serves starts answering
differently. Argus cannot see this today. It has no idea where a replica runs, so
nothing changed at the onset as far as it can tell, and no action it can take
addresses where a replica is placed.

## What Changes

- **Argus reads where each replica runs.** The deployment platform's read port
  gains `placements_of`, which returns each pod's node, the accelerator that node
  carries and when the pod started. The Argo CD adapter reads the resource tree's
  `Node` info item and the `nvidia.com/gpu.product` label on `hosts[].labels`. A
  read tool, `get_placements`, exposes it.
- **The Investigator records the placement before the model is asked.** It reads
  the placement as a fixed read after the onset is measured, as it does the
  metrics. It shows the placement to the model and publishes it as an event,
  together with the onset it was read against, so the timeline and the
  postmortem state it. It returns it on the findings.
- **The recorded placement reaches strategies through `Circumstances`.** It is
  one new field, so no signature changes.
- **A new mode, `accelerator-heterogeneity`.** The service's answers changed
  with no revision at the onset, and a replica began running on a different
  accelerator at that minute. It is told apart from `output-quality-degradation`,
  where a revision sits at the onset.
- **A new generic mitigation, pinning a deployment to an accelerator.** It is a
  merge patch of the Deployment's `nodeSelector` through Argo CD, with automated
  sync suspended for the pin. The accelerator to pin to is the one the replicas
  that started before the onset ran on, as recorded, and is never read at the
  moment of acting. When that is ambiguous no action is proposed: the suspect is
  also on a good replica, there is no suspect, there is more than one good
  accelerator, or no accelerator is labelled. The undo removes the pin and puts
  sync back.
- **The Target Service stages it.**
  - A new fraud scorer is pure Python. It emulates TF32 rounding on Ampere, and
    `ALLOW_TF32 = True` on `main` is the fault.
  - The resource tree gains one pod per replica, with nodes and GPU labels.
  - Scenario `scorer-replica-rescheduled` moves one replica from a V100 node to
    an A100 node at the onset, with no deploy, so the share of purchases held
    for review rises.
  - A new gauge, query and `gt` rule watch that share.
  - Pinning to V100 ends it.
- An e2e case, a paid `both` recording (approval to be asked for), a graded
  fix, an eval case, a Prometheus contract query, the spec and the backlog.

## Capabilities

### New Capabilities
- `accelerator-placement`: reading where each replica runs and on which
  accelerator, through the port and the read tier, and recording it with the
  onset before any action.
- `accelerator-pinning-mitigation`: the mode, the pin to the pre-onset
  accelerator and its place in the generic set, when no pin is proposed, sync
  suspension, and the undo.
- `accelerator-heterogeneity-scenario`: the fraud scorer, the rescheduled
  replica, its telemetry and rule, the tree's placements, and the fault
  Code-Fix fixes.

### Modified Capabilities
- `mitigation-circumstances`: the circumstances carry the recorded placement.
- `investigator-cause-detection`: accelerator heterogeneity is a determinable
  mode, separated from output-quality degradation.

## Impact

- `argus_core`:
  - new `PodPlacement` and `RecordedPlacement` models;
  - a new `Circumstances` field and a new `Findings` field;
  - a `PlacementRecorded` event;
  - a new `FailureMode` value;
  - a new `PinToAccelerator` action and its undo descriptor.
- `deployment_platform`:
  - the reads port gains `placements_of`;
  - the writes port gains `accelerator_pin_of` and `pin_to_accelerator`;
  - the Argo CD adapter implements all three.
- `read_mcp_server` / `read_mcp_client`: `get_placements`.
- `write_mcp_server` / `write_mcp_client`: `pin_to_accelerator` and
  `restore_accelerator_pin`.
- `agent_investigator`: the fixed read, the event, the opening message, the
  brief and the findings.
- `orchestrator`: carries the placement on the state and into `the_circumstances`.
- `agent_mitigation`: the strategy, admission, perform and undo.
- `argus_narration`: the event's line.
- `Argus-Demo-Target-App`: the scorer, the scenario, the tree, the Deployment
  patch, the gauge, the rule and the stand-ins.
- `tests/e2e`, `tests/contract/prometheus`, `tests/eval`,
  `scripts/record_incident.py`, `scripts/seed_a_rehearsal.py`, one paid `both`
  recording.
- `docs/spec-and-architecture.md`, `docs/failure-modes-backlog.md`.
