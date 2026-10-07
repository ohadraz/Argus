## 1. The stand-in (Argus-Demo-Target-App; code first, tests after)

- [x] 1.1 `state.py`: hold the `automated` object (start `selfHeal: true`, `prune: false`) or `None`; `syncs_itself` derived as `IsAutomatedSyncEnabled` reads it; reset restores the start
- [x] 1.2 `app.py`: `ArgoCdAutomatedSync.enabled`; `PATCH /argocd/{application}` (merge only, `spec.syncPolicy` only, 400 otherwise); the application route reports the held policy; the rollback refusal reads `syncs_itself`; the `PUT .../spec` route removed
- [x] 1.3 Demo tests: suspend by patch and report `enabled: false` with `selfHeal` on; restore by `enabled: null`; rollback refused only while enabled; non-merge and out-of-policy patches refused; reset; the old `PUT` helpers and tests moved to the patch

## 2. The write tier (TDD)

- [x] 2.1 Propose `test_argocd.py`, `test_rolling_back.py`, `test_scaling.py`, `test_pinning.py` whole: suspension and restore are one `PATCH` each to the application route with the merge patches of the spec; an `automated` with `enabled: false` reads as not syncing; no spec path in any settings
- [x] 2.2 Implement `argocd.py` (`a_sync_patch`, the constants, `is_reconciling_itself` reading `enabled`), and `put` → `patch` in the three modules
- [x] 2.3 Remove `argocd_spec_path` from `Settings`, the three slices and `.env.example`
- [x] 2.4 Propose `write_mcp_client`'s `fake_deployment_platform.py` (answers the application patch, holds the policy) and `test_client.py`'s suspension assertion (`enabled: false`, `selfHeal` kept), whole

## 3. End to end

- [x] 3.1 Propose the edits to `tests/e2e/framework/world.py` and `tests/e2e/test_withdrawing_an_incident.py`: "syncing" is `automated` present with `enabled` not `false`
- [x] 3.2 Full `e2e_replay(mode='both')`, free

## 4. Docs

- [x] 4.1 Spec §13: suspension switches automated sync off and leaves the rest of the policy as found

## 5. Review before commit

- [x] 5.1 lint, typecheck, guard_layering, test_all, integration, full e2e_replay
- [x] 5.2 Comments, docstrings, jargon, docs aligned; no missing, redundant or weak tests
- [ ] 5.3 Commit the demo app and Argus (one line each, approved); push the demo app immediately before Argus, since its stand-in no longer answers the route Argus's `main` calls (PowerShell); archive the change
