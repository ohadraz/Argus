## 1. The shop's scorer and scenario (Argus-Demo-Target-App; code first, tests after)

- [x] 1.1 `io_shop/fraud_scoring.py`:
  - `ALLOW_TF32 = True` and the TF32 accelerators;
  - `score` with 10-bit-mantissa rounding where TF32 applies;
  - `held_for_review(price, accelerator)`, with no random draw;
  - weights and threshold chosen so a measurable share flips on A100.
- [x] 1.2 Generator:
  - a `Rescheduling` condition, the `1/replicas` share scored by the moved replica (assigned by purchase index, no new draw);
  - `fraud_held_for_review_ratio` on `GeneratedMinute`, `MetricBucket` and `_the_buckets`.
- [x] 1.3 Exposition gauge, the Prometheus stand-in's `avg(fraud_held_for_review_ratio)`, and the rule `io-shop-fraud-holds-high` (`FraudHoldsHigh`: mean over 2m, `gt`, pending 5m) in `SERIES_RULES` and `_WHAT_FIRED`.
- [x] 1.4 Argo CD stand-in:
  - the tree carries one pod per replica, each with a `Node` info item, plus `hosts[].labels` carrying `nvidia.com/gpu.product`;
  - the moved pod is on A100 with `createdAt` at the onset;
  - `POST .../resource` accepts a Deployment merge patch on the GPU node selector only;
  - the manifest shows the selector;
  - `reset()` clears it.
- [x] 1.5 Scenario `scorer-replica-rescheduled`:
  - family "AI-specific", no deploy, no flag;
  - `seed`, `phase` and `generated_window` branches;
  - a pin to V100 ends the stretch and re-places the pods, while any other pin and the removal do not;
  - a log line at the onset;
  - a console entry and a "held for review" column.
- [x] 1.6 Demo tests:
  - scorer V100 and A100 behaviour (the A100-with-TF32 path only in `tests/target_app`);
  - the held share rises and nothing else moves;
  - the rule fires and resolves on the pin;
  - the tree's placements in and out of the scenario;
  - the patch's refusals;
  - `tests/io_shop` green on `main` with the fault uncovered.
- [x] 1.7 Commit the demo app (one line, approved) and push it (PowerShell).

## 2. The kernel (argus_core)

- [x] 2.1 Test first: `PodPlacement` and `RecordedPlacement`, with the onset rule (`started_before_the_onset`, `started_at_the_onset`). `Findings.placement` and `Circumstances.placement` are driven by 5.1 and 5.3.
- [x] 2.2 Implement them in `argus_core.models`.
- [x] 2.3 Test first: `FailureMode.ACCELERATOR_HETEROGENEITY` has a meaning that separates it from `output-quality-degradation` and `bad-deployment`.
- [x] 2.4 Implement the mode, its maintainer comment and its meaning.
- [x] 2.5 Test first: the `PlacementRecorded` event round-trips through `parse_event`.
- [x] 2.6 Implement the event and its union entry.
- [x] 2.7 Test first: `PinToAccelerator` has its subject, direction, service, platform and reversible tag; `AcceleratorPinUndo` parses.
- [x] 2.8 Implement the action, its `ActionType` and the undo descriptor.

## 3. The platform port and the Argo CD adapter (deployment_platform)

- [x] 3.1 Test first (`test_argocd.py`), `placements_of`:
  - the request shape;
  - pods with node, accelerator and start;
  - an unlabelled host gives no accelerator;
  - a pod with no `Node` item or no readable `createdAt` is left out;
  - 5xx is unreachable and 4xx is refused.
- [x] 3.2 Implement `placements_of` in the reads port and the adapter, with the wire names as `Final` constants.
- [x] 3.3 Test first, the two writes:
  - `accelerator_pin_of` reads the manifest's selector entry, or `None`;
  - `pin_to_accelerator` sends a Deployment merge patch with the label's value, and a null to remove it.
- [x] 3.4 Implement both writes.

## 4. The tiers

- [x] 4.1 Test first (`read_mcp_server`, `read_mcp_client`): `get_placements` returns the port's placements; a platform failure is a tool error.
- [x] 4.2 Implement `placements.py`, the server tool and the client function.
- [x] 4.3 Test first (`write_mcp_server`), `pin_to_accelerator`:
  - suspends sync where it was on;
  - builds the undo;
  - patches;
  - is exhausted when already pinned;
  - leaves the undo behind on an unreachable platform.
- [x] 4.4 Test first (`write_mcp_server`), `restore_accelerator_pin`: puts the selector back first, then resumes sync only where the undo says so.
- [x] 4.5 Implement `accelerators.py`, both server tools and both client functions, and extend the client's fake platform.

## 5. The walk

- [x] 5.1 Test first (`agent_investigator`):
  - the placement is read after the onset and before the first turn;
  - `PlacementRecorded` carries the onset;
  - the opening message marks onset-started pods;
  - an unreadable placement publishes `RetrievalUnanswered`, and the findings carry `None`.
- [x] 5.2 Implement the `fetch_placements` seam, the read, the event, the paragraph, the brief's paragraph and the findings field.
- [x] 5.3 Test first (`orchestrator`): `investigator_node` carries the placement onto the state; `the_circumstances` sets it; `assembling.py` wires `get_placements`. (The three callers moved to 5.8: what they pass is only observable through the pin strategy.)
- [x] 5.4 Implement.
- [x] 5.5 Test first (`agent_mitigation/accelerators.py`), the classification:
  - the one-minute grace;
  - one good accelerator and a suspect;
  - overlap;
  - no suspect;
  - two good accelerators;
  - an absent accelerator;
  - no placement.
- [x] 5.6 Test first (`agent_mitigation`):
  - `PinToAcceleratorStrategy` maps from the mode;
  - admission;
  - `_perform` and `_what_it_would_have_done`;
  - the undo and its binding.
- [x] 5.7 Implement.
- [x] 5.8 Test first (`orchestrator`): the three callers of `the_circumstances` pass the findings' or the state's placement, seen as an accelerator candidate answered by `PinToAccelerator`; then pass it, and drop the parameter's `None` default.

## 6. What a reader sees

- [x] 6.1 Test first (`argus_core`): `the_accelerator_of(action)` is a pin's accelerator, and `None` for any other action.
- [x] 6.2 Implement.
- [x] 6.3 Test first (`orchestrator`): the published `ActionTaken` carries the pin's accelerator.
- [x] 6.4 Implement (`ActionTaken.accelerator`).
- [x] 6.5 Test first (`argus_narration`): the placement line names each pod's accelerator and the onset-started pods; the pin's action line names the accelerator.
- [x] 6.6 Implement.

## 7. Contracts and evals

- [x] 7.1 Propose the Prometheus contract test's new query `avg(fraud_held_for_review_ratio)`.
- [x] 7.2 Propose the eval case `accelerator-heterogeneity-is-told-from-output-quality-degradation` at bar `UNMEASURED`, with its incident builder.
- [x] 7.3 Propose `fetch_placements` for the root suites' direct calls to `investigate`: `tests/integration/test_token_accounting.py`, `tests/integration/test_replay_logging.py` (two calls) and `tests/eval/test_investigator_eval.py`.

## 8. End to end

- [x] 8.1 Propose `RECORDED_ACCELERATOR_HETEROGENEITY`, its entry in `THE_RECORDINGS_THAT_MUST_CARRY_A_FIX`, and the e2e case.
- [x] 8.2 Add the `record_incident.py` entry; the `noxfile` leaves the case to `both`.
- [x] 8.3 Add a rehearsal rewrite in `seed_a_rehearsal.py`, taken from `both-categoriser-model-upgraded`: the mode is named, the pin is taken, the fix is submitted.
- [x] 8.4 Rehearse the case alone, free; then run the full `e2e_replay(mode='both')`, free.
- [x] 8.5 Ask for the paid `record(mode='both')`; remove the rehearsal set; record.
- [x] 8.6 Replay the case from the real recording; run `grade_fixes`; report the spend.

## 9. Docs

- [x] 9.1 Spec:
  - §9 / §10: the placement as a fixed read and its evidence;
  - §12 / §12.1: `get_placements`, the pin tool and its undo;
  - §13: the pin in the generic set, as a drain;
  - §21: the placement on the postmortem's timeline.
- [x] 9.2 Backlog: FM-33 built (scenario, what moved, what it added, near-miss, mitigated and not resolved), and the AI-specific family row covered.

## 10. Review before commit

- [x] 10.1 lint, typecheck, guard_layering, test_all, integration, contract, full e2e_replay.
- [x] 10.2 Check comments, docstrings, jargon and docs are aligned, and that no test is missing, redundant or weak.
- [ ] 10.3 Commit Argus (one line, approved); archive the change, filling the new specs' Purpose before the archive commit.
