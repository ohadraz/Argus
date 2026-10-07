## 1. The fix (TDD)

- [x] 1.1 Propose the tests: the tree is read under the platform's credential, and with no header where none is configured
- [x] 1.2 Send `headers_for(argocd_auth_token)` on the tree read; drop the private `_headers_for`

## 2. Review before commit

- [x] 2.1 lint, typecheck, write tier and client suites, full e2e_replay
- [x] 2.2 Commit (one line, approved); archive the change
