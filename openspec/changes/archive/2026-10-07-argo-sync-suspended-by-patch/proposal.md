## Why

Rollback, scale-out and the autoscaler pin all suspend Argo CD's automated sync by
`PUT /api/v1/applications/{name}/spec` with a body of `{"syncPolicy": {}}`. A real
Argo CD takes that body as the *whole* spec and replaces the application's spec
with it (`server/application/application.go:1089`, route at
`server/application/application.proto:428-432`), so every deployment-platform
action Argus takes would fail validation - or, with validation off, erase the
application's source and destination. The demo's stand-in reads only the sync
policy, which is why nothing has noticed. Restoring writes `{"automated": {}}`,
which also drops whatever `prune`, `selfHeal` and `allowEmpty` the operator had
set. FM-33's pin would copy all of this, so it is fixed first.

## What Changes

- Sync is suspended and restored through Argo CD's `PATCH
  /api/v1/applications/{name}` with a JSON merge patch that touches
  `spec.syncPolicy.automated.enabled` and nothing else: `false` to suspend,
  removed to restore. Every other part of the spec and of the sync policy is left
  as found.
- An application whose `automated` says `enabled: false` reads as not syncing
  itself, as Argo CD reads it.
- **BREAKING** (settings): `ARGOCD_SPEC_PATH` / `argocd_spec_path` is removed; the
  patch goes to `argocd_application_path`, which every action already reads.
- The demo Target Service's Argo CD stand-in answers the patch, keeps the sync
  policy it reports (with `selfHeal` on, as a GitOps application would have it),
  refuses a rollback only while automated sync is enabled, and drops its
  `PUT .../spec` route.
- The e2e checks that read "suspended" as `automated` being absent read it as
  `enabled: false`.

## Capabilities

### New Capabilities
- `automated-sync-suspension`: how Argus switches the deployment platform's
  automated sync off before a write and back on in an undo, what it leaves
  untouched, and how it reads whether an application syncs itself.

### Modified Capabilities

None. The three mitigation specs require suspension and restoration "to the state
it had"; that requirement is unchanged, and this change is what makes it true
against a real Argo CD.

## Impact

- `write_mcp_server`: `argocd.py`, `rolling_back.py`, `scaling.py`, `pinning.py`
  (the injected `put` becomes `patch`; the settings slices lose `argocd_spec_path`).
- `argus_core`: `config.py` loses `argocd_spec_path`; `.env.example` loses its line.
- Tests: `write_mcp_server`'s `test_rolling_back.py`, `test_scaling.py`,
  `test_pinning.py`; e2e `framework/world.py` and `test_withdrawing_an_incident.py`.
- Demo app: `app.py` Argo CD routes and models, `state.py` sync state, its tests.
- No recordings change: the write tier is not model-facing.
- Requires Argo CD 3.1 or later, where `automated.enabled` was introduced.
