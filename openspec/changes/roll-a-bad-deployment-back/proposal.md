## Why

`bad-deployment` is the only failure mode of the five that reaches no
mitigation: it is diagnosed, named, and then handed to a person. It is also the
most common shape of incident there is - change-induced failures are 31% of the
published taxonomy, and a deploy-induced regression is half of that family - so
the gap is the largest single piece of Argus's coverage that is missing, and the
one a reader of the failure-mode backlog notices first.

Nothing new has to be built to close it. The platform call that answers it is
already in the write tier: `roll_back_configuration(application)` takes no
revision, because the platform resolves the revision before the one running -
which is what rolling a bad deploy back means. What is missing is a strategy
registered for the mode, a scenario that is live enough to roll back, and a name
for the action that does not say "configuration" while returning a deployment.

## What Changes

- **BREAKING (internal): the rollback action is renamed to name the deployment
  rather than its configuration.** `ROLL_BACK_CONFIGURATION` becomes
  `ROLL_BACK_DEPLOYMENT`, `RollBackConfiguration` becomes `RollBackDeployment`,
  the write tool `roll_back_configuration` becomes `roll_back_deployment`, and
  the undo descriptor follows. One action kind serves both modes, because the
  platform call, the undo, and the grounds for taking it unasked are identical -
  a second kind performing the same call would be machinery bought for nothing.
- **The criterion for being a mode is dropped, not widened.** A failure mode is
  a classification of what broke, and the registry is a strategy lookup over it;
  a many-to-one map from modes to strategies is the ordinary shape of that
  pattern. Deriving a mode's identity from the strategy that answers it inverts
  the dependency - the vocabulary a human reads starts serving the dispatch
  table - so the test for a mode is whether a reader distinguishes it, and
  "the choice of mitigation is what dispatches on a mode" stops being a rule
  about which modes may exist. It keeps its original job, which is why the
  granularity it settled is unaffected: `resource-leak` is still one value
  rather than one per resource, because a heap and a pool are not distinct to a
  reader of an incident either.
- **`BAD_DEPLOYMENT` dispatches to the rollback strategy**, and the closed set
  of generic mitigations admits it on the same grounds as a config rollback: the
  revision restored was reviewed and already ran, so Argus replays somebody's
  change rather than authoring one.
- **The `bad-deployment` scenario becomes live.** It is authored minutes today,
  and says so: *"Authored, not live: there is no rollback to perform yet."* It
  gains a revision of the Target Service that is genuinely slower - the account
  page recomputing per item what it used to read once - a revision before it in
  the deploy history, and generated telemetry in which the p95 and p99 climb
  because the code is slow rather than because a fixture says so.
- **A withdrawal puts the newer revision back** and resumes the reconciliation
  the rollback suspended, as the config rollback's withdrawal already does.
- **An e2e case** drives diagnosis from the deploy history alone, then the
  mitigation, then the withdrawal - rehearsed free on fabricated answers, then
  recorded once against the real API so it replays.

## Capabilities

### New Capabilities
- `bad-deployment-scenario`: the live scenario - which revision is slow and why
  it is slow, what the telemetry does across the deploy, what the deploy history
  records, and that the incident is readable from that history alone because no
  log line mentions the deploy.

### Modified Capabilities
- `config-rollback-mitigation`: the action names the deployment rather than the
  configuration, and `bad-deployment` maps to the same strategy - so the
  requirement deriving a third *mode* from a third *action* is restated to
  derive the mode from the distinction a reader of an incident makes, with the
  mapping from modes to strategies stated as many-to-one.
Neither `generic-mitigation-tier` nor `argo-deploy-adapter` needs a delta,
though both are touched. The first decides autonomy by membership of a closed
set and never enumerates the kinds, so a renamed kind changes code and no
requirement. The second reads whatever history it is served; that the history
now carries a revision pair is the scenario's requirement, not the adapter's.

## Impact

- `argus_core.models`: the action type, the action, the undo descriptor,
  `FailureMode.BAD_DEPLOYMENT`'s stated lack of an answer, and the module's own
  prose - both the docstring and `CONFIG_INDUCED_FAILURE`'s comment argue from
  the criterion being dropped.
- `agent_mitigation`: the strategy registry and the renamed strategy class;
  `admitting` for the second mode.
- `write_mcp_server` / `write_mcp_client`: the tool name, its docstring, and the
  typed client function.
- `argus_narration`: the sentence said about a rollback, which must read
  correctly for a code deploy as well as a configuration change.
- Revision `001` of the schema, edited in place, for the persisted action-type
  value; no migration, since the schema is applied by dropping it.
- `Argus-Demo-Target-App`: a slower revision of `io_shop`, the scenario's
  generated minutes, its deploy history, and the demo suite covering the new
  code after the fact.
- One paid `record` run, for the new e2e case only.
- Recordings already committed are untouched: mitigation is deterministic
  policy, so no recorded model answer names the renamed tool.
