---
name: e2e-test-placement
description: Use when deciding where a test file belongs in this workspace, or when proposing a test that needs the docker-compose stack. Covers why e2e-marked tests live only in root tests/e2e/ and never inside a module's own tests/, and which nox session runs which directory.
---

A test's directory decides which nox session runs it, and therefore whether
anything has brought its dependencies up first.

## The rule

**`e2e`-marked tests live only in root `tests/e2e/`. Never inside a module's own
`modules/*/tests/`.**

Enforced by `nox -s guard_e2e_boundary` (also a pre-commit hook), so a
misplacement fails before it can confuse anyone.

## Why

- `nox -s test_module` filters to `-m "unit or integration"`, so an `e2e` test
  sitting in a module's `tests/` is silently skipped there - it looks like it
  passes.
- `nox -s test_all` runs each module's `tests/` **unfiltered**. That same test
  now runs with no docker-compose stack behind it, because only `nox -s e2e` and
  `nox -s e2e_replay` bring one up - and they point at root `tests/e2e/`, not at
  module directories.

So the test is either never run or run without its stack, and neither failure
mode announces itself as a placement problem.

## Where a test goes

| The test needs | Directory | Marker | Run by |
|---|---|---|---|
| nothing but the module | `modules/<name>/tests/` | `unit` | `test_module`, `test_all` |
| two or more modules, in-process | `modules/<name>/tests/` or root `tests/integration/` | `integration` | `test_module` / `integration` |
| the full stack over HTTP | root `tests/e2e/` | `e2e` | `e2e`, `e2e_replay` |
| a real external party the repo doubles | root `tests/contract/` | `contract` | `contract` |

A module-level behaviour that can only be exercised through the running stack
belongs in root `tests/e2e/` even though it is "about" one module. If that feels
wrong, it is usually a sign the module has no seam that can be tested without
the stack - which is a design finding worth raising, not a reason to move the
file.

Tag every test with exactly one marker; the list lives in the root
`pyproject.toml` and adding to it is a deliberate change.

Remember `tests/` is off-limits to Claude in this repo - propose the whole file
in chat (see `tdd-new-behavior`), correctly placed.
