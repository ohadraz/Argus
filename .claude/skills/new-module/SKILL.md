---
name: new-module
description: Scaffold a new module under `modules/` in the Argus uv workspace. Use when the user asks to add a new agent, service, or module to the project.
---

Given a module name (e.g., `agent-ratelimiter`), create:

1. `modules/<name>/pyproject.toml`:
   - `[project] name = "argus-<name>"`, `version = "0.1.0"`
   - `dependencies = ["argus-common", ...]` with `[tool.uv.sources]
     argus-common = { workspace = true }`
   - `[build-system]` using hatchling, `[tool.hatch.build.targets.wheel]
     packages = ["src/argus_<name_with_underscores>"]`
2. `modules/<name>/src/argus_<name_with_underscores>/__init__.py` - empty, just
   establishes the package.
3. `modules/<name>/tests/conftest.py` - minimal, shared fixtures placeholder.

Do NOT add anything else to `tests/` beyond `conftest.py` - actual test files are
off-limits for Claude to write (see CLAUDE.md "Tests are off-limits").

Do NOT edit `noxfile.py` - module discovery is automatic via `_discover_modules()`
scanning for `modules/*/pyproject.toml`. Confirm the new module appears by running
`uv run python -m nox --list` and checking for a new `test_module(module='<name>')` line.

The one exception: a module that deliberately has **no** test suite - test-support
code like `argus_testkit` or `anthropic_double` - is named in `EXCLUDED_FROM_TESTS`
at the top of `noxfile.py`, because pytest exits non-zero when handed a `tests/`
path that does not exist. That list is the only part of `noxfile.py` a new module
ever touches, and only for that case.

After scaffolding, run `uv sync` to confirm the workspace resolves the new member
correctly, and report any resolution errors rather than silently proceeding.
