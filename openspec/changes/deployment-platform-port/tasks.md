## 1. The module and the adapter (TDD)

- [x] 1.1 Scaffold `modules/deployment_platform/` (new-module skill); add to `root_packages` and the adapter-import contract
- [x] 1.2 Propose `deployment_platform_test/test_argocd.py`: every request's method, path, query, headers and body over `MockTransport`; each read's parse; unreachable vs refused
- [x] 1.3 Implement the port, values, exceptions, `ArgoCdSettings` and `ArgoCd`

## 2. Read tier (TDD)

- [x] 2.1 Propose rewrites of `test_argocd.py` (now `test_deploy_history.py`), `test_rollouts.py`, `test_deployments.py`, `test_server.py` against a faked `DeploymentPlatformReads`
- [x] 2.2 Move `argocd.py` (renamed `deploy_history.py`), `rollouts.py`, `deployments.py`, `server.py` onto the port

## 3. Write tier (TDD), one action at a time

- [x] 3.1 `test_rolling_back.py` proposed; `rolling_back.py` onto the port
- [x] 3.2 `test_scaling.py` proposed; `scaling.py` onto the port
- [x] 3.3 `test_pinning.py` proposed; `pinning.py` onto the port
- [x] 3.4 `test_restarting.py` proposed; `restarting.py` onto the port
- [x] 3.5 `server.py` wiring; delete `write_mcp_server/argocd.py` and its test; import lines in the client fake and the two e2e files

## 4. Review before commit

- [x] 4.1 Comments, docstrings, jargon, docs (spec §12) aligned; no missing, redundant or weak tests
- [x] 4.2 lint, typecheck, guard_layering, test all, integration, full `e2e_replay(mode='both')`
- [ ] 4.3 Commit (one line, approved); archive the change
