## 1. The fix (TDD)

- [x] 1.1 Propose the test: a resumed rollback, scale-out or pin with no outcome escalates, the flag provider unasked, no action taken
- [x] 1.2 Ask `change_landed` only for an action through the flag provider; docstrings and comments say why

## 2. Review before commit

- [x] 2.1 lint, typecheck, orchestrator module suite, integration, full e2e_replay
- [ ] 2.2 Commit (one line, approved); archive the change
