## Why

Every scenario Argus can currently handle is a step change: a flag flips, and the
next minute is visibly worse than the last. A whole class of real faults does not
look like that. A memory leak, a connection-pool exhaustion, a disk filling up -
each is a slow climb over hours, and Argus is measurably blind to it.

Measured against the current detector, on a 360-minute window at default
thresholds:

| input | true onset | reported onset | asks to widen? |
|---|---|---|---|
| step - flat, then high | minute 180 | minute 180 | - |
| ramp starting a third in | minute 120 | **minute 243** | no |
| ramp filling the window | before minute 0 | **minute 304** | no |

Two hours late, and silent about it. The cause is one line: the baseline is the
median of the window's **lowest half by value**, so on a ramp the baseline climbs
with the fault and the noise estimate becomes the slope itself. Because the
window's earliest minute never looks anomalous, the existing "widen the window"
trigger never fires, so Argus reports a confident wrong onset rather than asking
for more data. Every window derived from that onset - the logs read, the changes
considered, the money counted - then covers the wrong stretch of time.

## What Changes

- **Onset detection gains a second baseline.** Today's baseline is ordered by
  value; a new one is ordered by time, taken from the window's earliest minutes,
  and the onset is the earlier of the two answers. The value-ordered baseline
  still handles a window containing an older, resolved incident; the time-ordered
  one handles a ramp. When the leak predates the window, the earliest minutes are
  already elevated, so the existing widening trigger finally fires for this case.
- **Metric buckets carry resource usage.** Three new fields, each named for a
  metric that already exists in every monitoring stack rather than invented for
  this demo: `memory_used_bytes` (the working set), `memory_limit_bytes` (what it
  is measured against), and `process_start_time_seconds` (how a restart is seen).
  No orchestrator is assumed - these are Prometheus client-library and
  node-exporter staples, not `kube-state-metrics` ones.
- **BREAKING: the autonomy tier stops being about reversibility.** Today an action
  may be taken autonomously only if `can_be_undone` is true and an undo descriptor
  can be populated. A restart can be undone by nothing, and calling it
  irreversible would put the industry's most common first response behind a human
  gate while flipping a production flag stays automatic. The tier becomes what
  Google SRE calls a *generic mitigation* and ITIL calls a *standard change*:
  membership of a closed, pre-authorised set. The undo descriptor stops being the
  gate and goes back to being what it is - how the walk unwinds a mitigation whose
  hypothesis was refuted.
- **Restart becomes a mitigation Argus can take**, through the write tier, shaped
  like Argo CD's own restart resource action. Guarded by a cap on restarts per
  incident rather than by human approval, because the real failure mode of a
  restart is repetition, not irreversibility.
- **The Target Service grows a leak scenario**: an accumulating fault in
  `io_shop` that is genuinely in the source, telemetry in which memory climbs and
  latency follows, logs that name the leak, and a restart control that reclaims
  it. A restart mitigates and does not resolve, so the walk ends mitigated and
  goes on to Code-Fix - which is the first scenario where that path is the
  *correct* one rather than a fallback.

## Capabilities

### New Capabilities

- `resource-metrics`: memory usage, its limit, and process start time carried
  from the Target Service through the read tier to the model, with per-minute
  aggregation semantics stated for gauges rather than rates.
- `trend-onset-detection`: finding the start of a sustained rise, so that a fault
  which ramps is dated where it began and a window that opens inside one asks to
  be widened.
- `generic-mitigation-tier`: autonomy decided by membership of a closed,
  pre-authorised set of mitigations rather than by whether an action can be
  undone; undo demoted to the unwind mechanism it already is.
- `restart-mitigation`: restarting the service as a generic mitigation - the
  write-tier tool, the strategy that proposes it, the cap that bounds it, and the
  verification that reads the reclaim back out of the metrics.
- `memory-leak-scenario`: the Target Service's leak - the accumulating fault in
  source, the telemetry it produces, the restart control that reclaims it, and how
  the scenario is graded.

### Modified Capabilities

- `investigator-react-loop`: the onset requirements gain the ramp case, and the
  "no visible start" trigger has to fire for a window that opens mid-climb.
- `flag-revert-mitigation`: "a reversible action is chosen from the cause" becomes
  "a generic mitigation is chosen from the cause"; the undo descriptor stops being
  the autonomy condition.
- `write-mcp-server`: a restart tool, and the tier rule it is admitted under.
- `two-phase-retrieval`: the metrics summary carries the three resource fields.
- `flag-driven-telemetry`: every generated bucket reports resource usage, not only
  the leak's.
- `target-service-scenario-control`: a scenario whose live condition is a restart
  rather than a flag, and the control that performs one.

## Impact

- **Argus**: `argus_core.models.metrics` (three fields), `argus_core.anomaly` (the
  trend arm), `agent_mitigation.strategies` (the tier criterion and a restart
  strategy), `write_mcp_server` + `write_mcp_client` (the tool), `argus_narration`
  (saying what a restart did), `agent_investigator` (a new `FailureMode`).
- **`Argus-Demo-Target-App`**: the accumulating fault in `io_shop`, the generator's
  resource metrics, the leak scenario, and a restart endpoint.
- **Spec**: §13's tier table and its four enforcement layers, and §21's "zero
  irreversible actions without human approval" metric, which is worded against the
  tier names this change replaces.
- **Tests**: the three new bucket fields reach roughly a dozen test builders across
  modules; every one is a file Claude may not edit, so they arrive as proposals.
