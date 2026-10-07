## Context

Three write-tier actions change live state under Argo CD - `rolling_back.py`,
`scaling.py`, `pinning.py` - and each suspends automated sync first, through its own
`_set_sync_policy`, which `PUT`s `argocd.a_sync_policy(reconciling)` -
`{"syncPolicy": {}}` or `{"syncPolicy": {"automated": {}}}` - to
`argocd_spec_path`. Against a real Argo CD that route is `UpdateSpec`, whose HTTP
binding is `body: "spec"` and whose handler is `a.Spec = *q.GetSpec()` followed by
validation. The demo stand-in reads `body.syncPolicy.automated is not None` and
nothing else, so the suite has always passed.

Each action records `was_syncing_itself: bool` in its undo record; the undo
re-enables only where that is true. `argocd.is_reconciling_itself` reads the
presence of `automated`.

Argo CD 3.1 added `spec.syncPolicy.automated.enabled` (`*bool`; nil means enabled),
and its own `SyncPolicy.IsAutomatedSyncEnabled()` - which the rollback handler uses
to refuse a rollback - reads `Automated != nil && (Enabled == nil || *Enabled)`.

## Goals / Non-Goals

**Goals:**
- Suspend and restore sync by a request a real Argo CD accepts and that changes
  only the switch.
- Read "syncs itself" exactly as the platform does.
- The stand-in behaves as the real route does, for the patch Argus sends.

**Non-Goals:**
- A conditional undo for deployment actions (whether somebody changed the policy
  since). Deployment undos stay unconditional, as `undoing.py` documents.
- An Argo CD contract test. None exists for any Argo route; adding one needs a
  cluster and an Argo CD, and is a change of its own.
- Argo CD before 3.1.

## Decisions

### D1. `PATCH /api/v1/applications/{name}` with a merge patch
Body `{"name": <application>, "patch": <JSON string>, "patchType": "merge"}`, the
`ApplicationPatchRequest` binding (`body: "*"`), sent to `argocd_application_path`.
The merge patch is applied to the whole Application, so the patch is rooted at
`spec`. *Alternative:* read the spec and `PUT` it back with the policy changed -
rejected: a read-modify-write races any other writer and still replaces the spec
wholesale.

### D2. The switch is `automated.enabled`, not the `automated` object
Suspend: `{"spec":{"syncPolicy":{"automated":{"enabled":false}}}}`. Restore:
`{"spec":{"syncPolicy":{"automated":{"enabled":null}}}}` - a merge-patch `null`
removes the key, which the platform reads as enabled. The operator's `prune`,
`selfHeal`, `allowEmpty` are never in a body Argus sends, so the undo record stays
`was_syncing_itself: bool`. *Alternative:* remove `automated` and record it whole
for the undo - works on any version, but puts an Argo object in the kernel's undo
record and touches every module's tests. The user chose this decision.

Restoring `null` rather than `true`: what Argus found was absent-or-true, which
the platform reads identically, and absent is what an operator's manifest usually
says - so the application is left as a declarative source would describe it.

### D3. The vocabulary in `argocd.py`, the requests in each action
`argocd.py` keeps no request code (its own docstring's rule). `a_sync_policy` is
replaced by `a_sync_patch(application, reconciling) -> dict[str, Any]`, the whole
request body, with the wire names as `Final` constants (`ENABLED`, `PATCH`,
`PATCH_TYPE`, `MERGE`, `NAME`). `is_reconciling_itself` reads
`automated is not None and automated.get(ENABLED) is not False`. Each module's
`_set_sync_policy` swaps `put` for `patch` (`HttpPatch`, default `httpx2.patch`)
and the spec path for the application path; its exception policy is unchanged.

### D4. `argocd_spec_path` is removed
From `Settings`, from the three slices and from `.env.example`. Nothing else
reaches that route, and a setting nothing reads is a place to configure Argus that
does nothing.

### D5. The stand-in holds a sync policy, not a boolean
`state` keeps the `automated` object (start: `selfHeal: true`, `prune: false`,
no `enabled`) or `None`; `syncs_itself` derives from it as the platform does; reset
restores the start. `PATCH /argocd/{application}` takes the request body, refuses a
`patchType` other than `merge` with 400, applies RFC 7386 to `{"spec": {"syncPolicy":
...}}`, refuses a patch reaching anything outside `spec.syncPolicy` with 400 (the
stand-in has nothing else to change), and returns the application. The `PUT
.../spec` route goes. `ArgoCdAutomatedSync` gains `enabled: bool | None`.

### D6. The e2e checks read the switch
`world._argos_automated_sync` and `test_withdrawing_an_incident._the_shop_reconciles_itself`
read "syncing" as `automated` present and `enabled` not `false`, mirroring D3.

## Risks / Trade-offs

- [An Argo CD before 3.1 drops the unknown `enabled` field] → suspension silently
  does nothing there, and the rollback is then refused by the platform as before.
  Stated in the settings comment; 3.1 is below every supported release.
- [Restore removes an explicit `enabled: true`] → read identically by the platform;
  accepted for D2's reason.
- [No contract test for the Argo routes] → the request shape is taken from Argo CD's
  own proto and handler, cited in the code; the stand-in mirrors it.

## Migration Plan

No stored state changes shape: undo records keep `was_syncing_itself`. An
environment setting `ARGOCD_SPEC_PATH` becomes ignored (settings ignore unknown
keys). The demo app is pushed before Argus, since Argus's CI checks out its
default branch.

## Open Questions

None.
