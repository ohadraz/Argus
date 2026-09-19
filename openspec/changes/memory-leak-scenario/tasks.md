## 1. Resource metrics reach the model

- [x] 1.1 Add `memory_used_bytes`, `memory_limit_bytes` (nullable) and `process_start_time_seconds` to `MetricBucket`, with the per-minute aggregation rule stated in the docstring - max for usage, last observed for the other two
- [x] 1.2 Propose the test-builder updates in chat, one whole file per message, for every suite whose builders construct a `MetricBucket`
- [x] 1.3 Emit the three fields from the Target Service's generator for every minute, staged scenario or not: a steady baseline well under the limit, and an unchanging start time
- [x] 1.4 Carry the three fields through `read_mcp_server`'s metrics summary and `read_mcp_client`, and confirm nothing drops them on the way
- [x] 1.5 Show memory in the narration and on the incident page beside the existing bucket columns
- [x] 1.6 `nox -s test_all` green, `guard_written_columns` green

## 2. The detector sees a trend

- [x] 2.1 Add a time-ordered calm stretch beside the value-ordered one in `argus_core.anomaly`, deriving a second departure threshold from the window's earliest minutes
- [x] 2.2 Mark a bucket anomalous when `memory_used_bytes` departs, alongside `error_rate` and `p95_ms`
- [x] 2.3 Make `find_onset` report the earlier of the two baselines' onsets
- [x] 2.4 Confirm `earliest_bucket_is_anomalous` now fires for a window filled entirely by a climb, so the walk widens
- [x] 2.5 Propose the `test_anomaly.py` cases in chat: ramp dated at its start, step unchanged, earlier resolved departure not chosen, full-window ramp widens, memory-only departure
- [x] 2.6 Re-run the ramp probe from this session's scratchpad and record the before/after numbers in the change's notes

## 3. The autonomy tier becomes membership

- [x] 3.1 Declare the closed set of generic mitigations in `agent_mitigation`, replacing `can_be_undone` as the gate's question
- [x] 3.2 Make the undo descriptor optional on an action, with "nothing to put back" a recorded state distinct from "not yet answered for"
- [x] 3.3 Leave the unwind path alone for actions that have a descriptor, and make it skip - without reporting a failure - for actions that never had one
- [x] 3.4 Add the per-incident, per-subject cap on a repeatable mitigation, with a refusal that names the cap **(deferred into group 4: there is no repeatable mitigation to cap until the restart exists)**
- [x] 3.5 Update the Orchestrator's gate node and the refusal vocabulary to match
- [x] 3.6 Propose the test updates in chat for `agent_mitigation` and the Orchestrator's gate

## 4. Restart as a mitigation

- [x] 4.1 Add a restart tool to `write_mcp_server`, shaped like a platform restart action, returning the service and the new process start time
- [x] 4.2 Expose it as a typed function on `write_mcp_client`
- [x] 4.3 Return no undo descriptor from it, and say explicitly that nothing was changed that can be restored
- [x] 4.4 Add `RESOURCE_LEAK = "resource-leak"` to `FailureMode`, and the strategy mapping it to a restart
- [x] 4.5 Verify a restart in two steps: the start time changed (it landed), then memory fell and symptoms eased (it helped) - recorded as different outcomes
- [x] 4.6 Confirm a confirmed restart routes to Code-Fix and the incident ends mitigated rather than resolved
- [x] 4.7 Propose the test updates in chat for the write tier, the strategy and the verification

## 5. The Target Service leaks

- [ ] 5.1 Write the accumulating fault into `io_shop` - state retained per request, never released - reachable by reading the code and uncovered by the existing suite
- [ ] 5.2 Compute resource usage from process uptime rather than from a script: memory climbs while up, resets on restart, climbs again
- [ ] 5.3 Make latency follow memory as the limit nears, and the error rate rise only once the service is failing
- [ ] 5.4 Emit the log lines - heap against its limit, then termination and restart
- [ ] 5.5 Add the restart control under the scenario-control prefix, reclaiming what the scenario accumulated, with the same effect whoever calls it
- [ ] 5.6 Register the scenario, hidden from the console until it plays well
- [ ] 5.7 Cover the new demo-app behaviour with tests written after the code, as that repo's convention has it

## 6. The spec says what the system now is

Written as a specification rather than a changelog, per the `spec-doc-style`
skill - the design as though it had always been the intent, with no note
appended about what it used to say. "Reversible" is load-bearing in twenty
places, so this is a pass over the whole document, not two sections.

- [ ] 6.1 §13: rewrite the tier table and the four enforcement layers around membership of a closed set; the gate node's row stops asking for a populated undo descriptor and asks whether the kind is admitted
- [ ] 6.2 §3 and §21.2: reword the "0 irreversible actions without human approval" success criterion against the tier names that replace it
- [ ] 6.3 §1, §2 and §4: the framing lines that say Argus "mitigates reversible causes" and "takes real (reversible) actions", and the principle naming the four tiers
- [ ] 6.4 §7.3: the Mitigation agent proposes a generic mitigation, and the undo descriptor is how a refuted one is put back rather than what admits it
- [ ] 6.5 §10: "no reversible action left to try" on the `mitigating --> fixing` edge, and the paragraph arguing what admits the walk
- [ ] 6.6 §11.1: the ERD's `bool reversible` and `jsonb undo_descriptor` columns, and §11.4's argument that the gate needs a deterministic answer about the descriptor
- [ ] 6.7 §12.1: the write tier's tool table gains the restart, in the tier vocabulary that replaces "reversible tier"
- [ ] 6.8 §16: the metrics channel carries the three resource fields
- [ ] 6.9 §15.2 and §15.3: the leak's row - seeded state, what the anomaly reacts to, that it never stops via a flag, and that correct behaviour is restart then propose a fix
- [ ] 6.10 §21.1: the leak joins the benchmark scenarios as the first that ramps rather than steps
- [ ] 6.11 Read the whole document once through for "reversible" and for any claim this change has outgrown
- [ ] 6.12 The same pass over the code's own prose: seventeen docstrings and comments still argue from reversibility - `proposing.py` and `fixing.py` in their opening lines, `mitigating.py` in both modules, the two MCP tool registrations, `incident_status.py`, `hypothesis.py`, and the incident page's account of `undone`. A flag revert is still reversible and still says so; what has to go is reversibility given as the *reason* an action may be taken unasked

## 7. End to end

- [ ] 7.1 Add the e2e case: leak staged, onset dated at the climb's start, restart taken, memory reclaimed, incident ends mitigated with a fix proposed
- [ ] 7.2 Record the replay fixtures for the new case under both code-search modes
- [ ] 7.3 Confirm the scenario is graded by the repository's test suite against the fix branch, and is *not* graded resolved by the telemetry going quiet
- [ ] 7.4 `nox -s e2e_replay(mode='both')` green
- [ ] 7.5 One real `nox -s e2e` run before merge, with the token spend reported
