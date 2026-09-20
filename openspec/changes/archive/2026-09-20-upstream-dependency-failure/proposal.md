## Why

Every incident Argus can handle today is one of its own: something inside the
deployment changed or accumulated, and reverting or restarting it helps. The
second-largest family of real incidents is not like that - 28% of them
propagate in from outside, and the correct response is to recognise that
nothing in reach will help and hand the incident to a person.

Argus has the escalation path already; what it has never been shown is an
incident where escalating is the *right* answer rather than what is left when a
diagnosis failed. Today "escalated" means the Investigator found nothing. An
incident that is diagnosed confidently, named exactly, and escalated anyway is
the one case that proves the judgement is real - and it is the case that stops
a confident agent from reverting an innocent flag because reverting is what it
knows how to do.

## What Changes

- **The shop depends on something it does not own.** `io_shop` calls a payment
  provider to authorise a checkout, in source, over HTTP. The dependency is
  real code on the request path, not a flag: its failures arrive as timeouts and
  5xx, are retried the way a real client retries, and surface as the shop's own
  error rate.
- **A scenario that fails the dependency and nothing else.** Seeding
  `upstream-dependency-failure` makes the provider refuse. No flag moves, no
  deploy record changes, memory stays flat, and the shop's own code is
  blameless - so every signal Argus knows how to act on is silent, and the only
  channel that says anything is the log, which names the upstream by host and
  status.
- **A failure mode for it.** `FailureMode.UPSTREAM_DEPENDENCY_FAILURE`, mapped
  to no mitigation strategy. The mapping's absence is the decision: the closed
  set of generic mitigations is what Argus may do unasked, and there is no
  generic mitigation for somebody else's outage.
- **The refusal names the mode.** Today a determined cause nothing answers and
  a flag the provider never recorded reach the same sentence - "no mitigation
  was proposed for this cause" - because both arrive at the gate with no
  action. They are different situations: one is a gap in the evidence, the
  other is a decision. A refusal of its own says the mode was determined and
  nothing in the closed set answers it.
- **Grading stays honest.** The scenario has no Argus-controllable condition,
  so the anomaly never stops. An agent that reverted a flag to try would be
  graded by telemetry that keeps failing, with no separate "mark wrong" logic.

## Capabilities

### New Capabilities

- `upstream-dependency-scenario`: the shop's outbound payment dependency, the
  scenario that fails it, the telemetry and logs it produces, and the rule that
  no Argus action ends it.

### Modified Capabilities

- `investigator-cause-detection`: the mode is determinable from evidence, and
  the scenario is added to what the Investigator is asked to recognise.
- `generic-mitigation-tier`: a determined mode that no member of the set
  answers is refused in its own words, distinct from an action nobody could
  identify.
- `target-service-scenario-control`: a scenario whose condition is external -
  seeded and cleared through the demo's own control, never by a mitigation.

## Impact

- **Argus**: `argus_core.models.failure_mode` (one value) and `Refusal` (one
  value), `orchestrator.walk.gating` (which refusal is given),
  `argus_narration` (the sentence it reads as), `agent_investigator`
  prompting.
- **`Argus-Demo-Target-App`**: the payment client on the checkout path, the
  provider stand-in it calls, the scenario, its generated telemetry and logs.
- **Spec**: §15.3's scenario table gains the row's detail; §7.3's escalation
  wording separates the two reasons.
- **Tests**: a new e2e case, and recordings for both `CODE_SEARCH` modes -
  `record` spends tokens, so the recordings are a deliberate step.
