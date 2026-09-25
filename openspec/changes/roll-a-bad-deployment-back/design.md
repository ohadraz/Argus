## Context

`BAD_DEPLOYMENT` is diagnosed and answered by nothing: `DEFAULT_STRATEGIES`
registers three modes, and it is not one of them. The action that would answer it
already exists - `roll_back_configuration(application)` on the write tier, which
takes no revision because the platform resolves the one before the one running -
and so does the stand-in that performs it: the demo app *is* the Argo CD double,
and its rollback endpoint refuses while automated sync is on and refuses an
unknown history entry, exactly as the platform does.

Two things stand in the way. The action's whole vocabulary says *configuration*,
which would make the sentence a human reads about a rolled-back code deploy
false. And the scenario cannot be mitigated at all: it is authored minutes, and
its own description says so - *"Authored, not live: there is no rollback to
perform yet."*

## Goals / Non-Goals

**Goals:**

- `bad-deployment` diagnosed, mitigated, verified and withdrawn, end to end,
  with the diagnosis reachable only from the deploy history.
- One action kind answering two modes, named for what it does.
- A scenario whose slowness is real code at a real revision, so that what remains
  after the mitigation is a fix Code-Fix could write.

**Non-Goals:**

- A fourth mitigation kind. The platform call, the undo and the grounds for
  autonomy are identical to the config rollback's; a second kind would be the
  same call under a second name.
- Resolving the incident. A rollback mitigates; the branch still holds the
  regression, and re-enabling reconciliation brings it back.
- Any change to how autonomy is decided. `GENERIC_MITIGATIONS` is a set of
  three *kinds*; renaming one leaves it a set of three, and a second mode
  mapping onto one of them asks it nothing new.

## Decisions

### The regression is the lifetime average recomputed per purchase

The bad revision makes `average_spend_per_item` derive the total from the
purchases once per purchase instead of dividing the total the account already
carries - the prefix-sum shape somebody writes on the way to a trend chart,
keeping only the last row. Same figure, quadratic cost, and it sits on the
always-on path, so every request pays it and the median moves with the tail.

*Alternative considered and rejected:* shipping the typical-spend figure to
everyone by removing its rollout guard, which is where this started. The guards
select between the three figures in order, so typical spend winning
unconditionally makes `use_monthly_summary` unreachable - and the monthly
summary's divide-by-zero is the fault three flag scenarios are built on. A
change that quietly disarms other scenarios is the wrong regression however
convenient its slowness.

*Why the working tree can carry it at all:* the generator renders real pages but
does not time them - `_what_the_page_cost` computes a minute's latency from the
staged scenario (`walked_once_per_item`, `items_bought`, whether the cache
answered). So slow source is inert for every other scenario, while the diff is
real for whoever reads or fixes it. It also means this scenario's own telemetry
comes from a scenario flag, exactly as the cache scenario's does from
reachability, rather than from how the code happens to be written.

*Consequence to watch:* the shape still reads as "a flag was toggled" to a model
that has seen the flag scenarios. Nothing in the window supports that - no flag
change is recorded - so the discrimination is honest, and it is the
discrimination this scenario is worth having for.

### One action kind, renamed rather than added

`ROLL_BACK_CONFIGURATION` becomes `ROLL_BACK_DEPLOYMENT`; `RollBackConfiguration`
becomes `RollBackDeployment`; `ConfigRollbackUndo` becomes `DeploymentRollbackUndo`;
the write tool `roll_back_configuration` becomes `roll_back_deployment`, with the
client function following. One revision carries the code and the configuration it
was deployed with, so the platform's rollback is one operation over both, and the
mode is what says which of the two broke.

*Alternative considered:* leave the names and register the strategy anyway.
Rejected - narration would tell a human a configuration was rolled back when new
code was.

### The criterion that made modes and mitigations one-to-one is dropped

`config-rollback-mitigation` derives a third mode from a third action. That is
backwards: a `FailureMode` classifies what broke, the registry is a strategy
lookup over it, and many-to-one is the ordinary shape of that pattern. Deriving a
mode's identity from its handler inverts the dependency - the vocabulary a human
reads starts serving the dispatch table. The rule keeps its original job, which
was to justify naming patterns rather than triggers, and the granularity it
settled is unaffected: `resource-leak` stays one value because a heap and a pool
are not distinct *to a reader*, which is the test that replaces it.

What still separates the two modes now sharing an action is what each one's fix
changes - a values file for a broken configuration, the service's source for a
bad deployment - and that distinction is already in the specs.

### The rename lands first, alone, with the suites green

It is 26 files and no behaviour, so it goes in as its own commit ahead of
everything else: a green `test_all` after it is the evidence that the rename
changed nothing, and nothing later has to be read twice to see whether a failure
came from the rename or from the new mode.

Fourteen of the files are test files, which Claude may not edit. They are 124
occurrences of thirteen identifiers and not one line of test *logic*, so the
human applies them with one command rather than pasting fourteen files. The
substitutions are ordered longest-first, because several are prefixes of others:

```
files=$(grep -rlE "RollBackConfiguration|ROLL_BACK_CONFIGURATION|ConfigRollbackUndo|Configuration(Restored|Roller|Restorer)|configuration_(roller|restorer)_over|roll_back_configuration|restore_configuration|roll-back-configuration|config-revision" --include="*.py" modules/*/tests tests/)
sed -i "s/RollBackConfigurationStrategy/RollBackDeploymentStrategy/g; s/RollBackConfiguration/RollBackDeployment/g; s/ROLL_BACK_CONFIGURATION_TOOL/ROLL_BACK_DEPLOYMENT_TOOL/g; s/ROLL_BACK_CONFIGURATION/ROLL_BACK_DEPLOYMENT/g; s/ConfigRollbackUndo/DeploymentRollbackUndo/g; s/ConfigurationRestored/DeploymentRestored/g; s/ConfigurationRestorer/DeploymentRestorer/g; s/ConfigurationRoller/DeploymentRoller/g; s/configuration_restorer_over/deployment_restorer_over/g; s/configuration_roller_over/deployment_roller_over/g; s/restore_a_configuration/restore_a_deployment/g; s/roll_back_a_configuration/roll_back_a_deployment/g; s/restore_configuration/restore_deployment/g; s/roll_back_configuration/roll_back_deployment/g; s/roll-back-configuration/roll-back-deployment/g; s/config-revision/deployment-revision/g" $files
```

Two test-local constant names survive it and are worth a hand-edit afterwards:
`A_CONFIG_ROLLBACK` in `test_undo_descriptor.py` and `ROLL_BACK_TOOL` in
`test_tools.py` now hold renamed values under their old names.

Claude's half is the prose the identifiers sit in - docstrings, comments and spec
text that argue from "configuration" - which a substitution cannot do.

### The persisted value changes by dropping the schema, not by migrating

`action_type` is stored as a string. Revision `001` is the whole chain and is
edited in place, so `nox -s schema` is the whole of the data change. Committed
recordings are untouched: mitigation is deterministic policy, so no recorded
model answer names this tool.

### The demo app learns a second thing a rollback can end

`roll_the_configuration_back()` ends a cache outage and puts the working endpoint
back. It becomes the general "put the shop on the previous revision" hook: it
ends whichever stretch the deployed revision was causing - a cache outage, or the
slow rendering this scenario stages. The rollback endpoint's two refusals stay
exactly as they are, because they are the platform's behaviour and not this
scenario's.

## Risks / Trade-offs

- **A model reads the shape as a flag toggle** → the window records no flag
  change and the flag does not move; if an eval shows the confusion surviving
  that, the fix is the evidence the Investigator is shown, not the scenario.
- **The rename is wide and mechanical, and a missed occurrence fails at import**
  → it lands alone, and `test_all` plus `typecheck` over the whole workspace is
  the check; nothing else is in flight to confuse the failure.
- **The generator's slow stretch could be made to look like the canary's** →
  they are the same code and must not be the same telemetry: the canary's claim
  is that p50 and p95 do not move, this one's is that they do, so the two
  scenarios' assertions are each other's regression test.
- **One paid recording** → the walk is rehearsed for free first on fabricated
  answers (`scripts/seed_a_rehearsal.py`), so the paid run is spent on the
  model's judgement and not on discovering the plumbing.

## Migration Plan

1. The rename, alone, green.
2. The demo app: the slow revision, the scenario's generated minutes, the deploy
   history pair, the rollback hook. Its own tests after the code, as that repo's
   policy has it.
3. Argus: the strategy registration, the narration sentence, the withdrawal.
4. The e2e case, rehearsed free.
5. One `record(mode='both')` for the new case, then green under `e2e_replay`.
6. The docs: spec §7.3 and §13, `FailureMode`'s prose, and the backlog's
   change-induced row.

At archive time the spec folder `config-rollback-mitigation` is renamed to
`deployment-rollback-mitigation`, which is bookkeeping this change deliberately
does not do mid-flight.

## Open Questions

- Does the slow revision need its own commit on `main` of the demo repo before
  the scenario can name it, as `THE_COMMIT_THAT_MOVED_THE_CACHE_PORT` did? The
  hash is a literal in the scenario, so the commit comes first and the scenario
  names it afterwards - which means two commits in that repo, in that order.
- Is `bad-deployment`'s existing authored window kept anywhere as a fixture, or
  replaced outright? Replacing it is the intent. The investigator eval is
  unaffected - its `deploy-before-latency` case is a fixture of its own, not this
  scenario - but `tests/e2e/test_scenario_investigation.py` seeds this scenario
  and replays it, and there are 37 committed recordings under both modes' names.
  They were captured against the authored window, so after this change they are
  stale in the sense the `both` corpus already is: the plumbing still replays,
  and what the model said no longer answers the evidence it was shown. So the
  paid run re-records `bad-deployment` as well as the new mitigation case, and
  that is the whole of the extra cost this decision carries.
