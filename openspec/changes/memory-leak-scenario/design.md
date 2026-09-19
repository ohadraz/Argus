## Context

Argus handles step changes. Every scenario built so far - a flag flipped, a bad
deploy - makes the next minute visibly worse than the last, and the anomaly
detector is built around exactly that shape: a baseline taken from the window's
lowest half by value, and a departure measured in deviations from it.

A fault that ramps defeats that construction. Measured on a 360-minute window at
default thresholds, a climb beginning at minute 120 is dated at minute 243, and
one filling the whole window at minute 304. Neither triggers the existing
"window has no visible start" widening, because the earliest minute of a ramp
never looks anomalous against a baseline the ramp itself produced.

Three things have to change together for a leak scenario to work: the detector
has to see a trend, the metric vocabulary has to carry memory, and the autonomy
gate has to admit a restart. The third is the one that touches the safety story,
because the gate currently asks "can this be undone" and a restart cannot be.

## Goals / Non-Goals

**Goals:**

- Date a ramping fault at the minute the climb began, and widen the window when
  the climb predates it.
- Carry memory usage, its limit, and process start time end to end, named as
  metrics that already exist rather than invented for this demo.
- Let Argus restart a service on its own authority, bounded by a cap.
- Stage a memory leak in the Target Service that is a real accumulation in real
  code, gradable by the repository's own test suite.
- Make the mitigated-but-not-resolved path the correct outcome for the first
  time, rather than a fallback.

**Non-Goals:**

- Forecasting time-to-exhaustion (`predict_linear`-style). The fields make it
  possible; nothing in this change does it.
- Other resource faults - connection pools, file descriptors, disk. The
  detector change covers the class; only memory is staged.
- Recurrence. A restart reclaims and the climb resumes, which is how the
  generator works, but nothing opens a *second* incident when it climbs back.
  The seam is left where a later change can use it.
- Modelling a Kubernetes cluster. The restart is shaped like a platform's
  restart action; no orchestrator is assumed anywhere in the metric vocabulary.

## Decisions

### Two baselines, not a replacement

The value-ordered baseline stays and a time-ordered one joins it; the onset is
the earlier answer.

*Why not replace it.* The value-ordered baseline is what stops an older,
already-resolved departure inside the same window from being read as the current
incident - a documented reason in the existing code. A time-ordered baseline
alone would date the current incident from the earlier one.

*Why not a slope test instead.* Fitting a line and testing the gradient is the
textbook answer, and it introduces a second, differently-shaped notion of
"anomalous" that would need its own threshold, its own configuration and its own
explanation to the model. Reusing the existing departure machinery against a
different calm stretch answers the same question with the vocabulary already in
the module.

*Consequence worth noting.* When the ramp fills the window, the baseline drawn
from the window's opening is itself part of the climb, so the first minute to
clear it says where the window opens rather than where anything began. An onset
landing that near the opening is therefore reported as the window's own first
minute - a lower bound - and the existing widening fires on it. That is not a
side effect to work around; it is the correct behaviour, arriving through the
trigger that already exists.

*Measured, on a 360-minute window at default thresholds:*

| input | true onset | before | after |
|---|---|---|---|
| step, flat then high | 180 | 180 | 180 |
| ramp starting a third in | 120 | 243, no widen | 124, no widen |
| ramp filling the window | before 0 | 304, no widen | **0, widens** |
| step whose calm opening is a fifth | 72 | - | 72, no widen |
| resolved departure, then the real one | 240 | - | 240, no widen |

The three constants the opening's baseline needs were swept rather than chosen,
and each bound is a different phenomenon: the opening has to be about a tenth of
the window (longer and a genuinely visible start gets read as no start at all;
shorter and a climb older than the window clears its threshold too far in to be
recognised), it has to be credited with a far larger minimum spread than the
quiet half (three minutes cannot have seen a sampled rate's quantisation, and
0.5% reading as 1.0% for the next ten minutes is one sample, not an onset), and
an onset is believed as a start only past twice the opening's length (a ramp
measured against an opening of `n` minutes clears it at about `1.7n`).

### `memory_used_bytes` + `memory_limit_bytes`, not a percentage

Every real memory alert joins a usage gauge to a limit: `MemAvailable /
MemTotal < .10` on hosts, working-set against `kube_pod_container_resource_limits`
in Kubernetes. The pair is what is reported; the ratio is what is computed.

*Why not a ratio.* A ratio cannot be turned back into the pair, and the standard
forecast - when will this reach the limit - needs the absolute.

*Why a nullable limit.* A deployment with no configured limit is ordinary, and
reporting zero would make "0% used" and "no limit set" the same value.

### `process_start_time_seconds`, not `restarts_total`

`kube_pod_container_status_restarts_total` comes from kube-state-metrics, which
exists only in Kubernetes. `process_start_time_seconds` is exposed by default by
every Prometheus client library on Linux, and node_exporter has the host twin.
A restart is a *change* in the gauge, which is also how the standard alert is
written.

*Why it is needed at all.* Memory falling is ambiguous - the process restarted,
or traffic dropped. Without the start time, the verification of a restart cannot
tell "it did not land" from "it landed and did not help".

### Autonomy by membership, not by reversibility

The tier criterion becomes membership of a declared, closed set of generic
mitigations. The undo descriptor stops gating and goes back to being how a
refuted mitigation is unwound.

*Why not widen "reversible" to include a restart.* It would make the word mean
"reversible or nothing to reverse", which is a definition written around the
one action that broke it.

*Why not OR a second condition onto the gate.* That keeps a criterion the
industry does not use. Google SRE's generic mitigations are a closed set -
drain, roll back, restart, add capacity - applied before the cause is known, and
ITIL's standard change is pre-authorised for being routine, not for being
reversible. Both decide on membership. Argus's reversibility test happened to
fit because flag reversion was the only mitigation built.

*Why not require human approval for a restart.* It would put the industry's most
common first response behind a gate while flipping a production flag stays
automatic - backwards on any reading of blast radius.

*What replaces the safety it provided.* A cap on how many times one mitigation
may be applied to one subject in one incident. The real failure mode of a
restart is repetition, and a limit is the control operators actually use.

### Memory climbs from the last restart

The generator computes usage from how long the process has been running, not
from a script or from a flag's state.

*Why.* It is simpler than modelling "climb, then stop", it is what a leak
actually does, and it makes the restart honest: memory falls, and then climbs
again, because the fault is still in the code. It also means the scenario cannot
be graded by the telemetry going quiet - which is the property the scenario
exists to demonstrate, and the reason grading is the repository's test suite.

### The failure mode is `resource-leak`, not `memory-leak` or `resource-exhaustion`

The published taxonomy puts resource exhaustion at 13% of incidents and splits
it in two **by what the correct response is**: *demand saturation*, where a
correctly-sized resource met more load, answered by scaling out; and *resource
leak / runaway consumption*, growth uncorrelated with traffic, answered by
restarting and then fixing. That is exactly the level a `FailureMode` has to
name, because a `FailureMode` is what picks the mitigation.

*Why not `resource-exhaustion`.* It spans both sub-patterns, and they want
different actions. CPU saturation looks like a leak on a latency graph and a
restart makes it briefly better before it returns - which is the mistake a
system without the distinction makes.

*Why not `memory-leak`.* Too narrow. The same response is correct for a
connection pool never returned, a queue running away and a disk filling with
logs, and each would need a value of its own that mapped to the same strategy.
`docs/failure-modes-backlog.md` lists them as scenarios under this one mode.

### A restart is the scenario's live condition, replacing the flag

§15.2 requires a generated scenario to react to live state so that grading is
honest. For the leak, the live state is how long the process has been up. A flag
would be wrong twice: a flip hours before the alert falls outside every window a
reader retrieves, and no flag causes a leak.

## Risks / Trade-offs

**The tier change touches the most safety-sensitive part of the spec.** §13's
table and its four enforcement layers are the claim that Argus cannot act
irreversibly, and §21 measures it. → The set is closed and declared in one place;
an action of an unregistered kind is refused, exactly as today. The metric's
wording is updated with the tier names rather than left pointing at a criterion
that no longer exists.

**Two baselines can disagree, and the earlier answer is not always right.** A
window opening during an unrelated elevated period could date the onset too
early. → The value-ordered baseline still answers, and the earlier of the two is
taken only where both find a persisting run. Where the time-ordered baseline is
elevated at the window's edge, the answer is reported as a lower bound and the
window widens instead.

**Three new bucket fields reach about a dozen test builders**, every one a file
Claude may not edit. → They arrive as whole-file proposals, and the source change
lands first so the failures name exactly which builders need them.

**A restart cap that is too low makes the scenario unplayable; too high makes it
a restart loop.** → The cap is configuration, defaulted low, and a refusal names
it so the walk escalates rather than stalling silently.

**The leak must be fast enough to demo and slow enough to be a ramp.** → The
generator computes from process uptime, so seeding backdates the start; a demo
sees a full climb without waiting for one.

## Migration Plan

The three new bucket fields are additive and nullable where a deployment may not
supply them, so a Target Service that has not been updated still serves buckets
Argus can read. Order: the metric fields, then the detector, then the tier
change, then the restart tool, then the scenario - each landing green, with the
scenario last because it is the only step that needs all four.

## Open Questions

- Whether the restart cap belongs beside the mitigation settings or with the
  generic-mitigation set. Leaning to the settings slice the agent already holds.
