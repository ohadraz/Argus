# Argus - Project Context for Claude

## What this is
Argus is an autonomous incident-response agent (course project). Full spec:
`docs/spec-and-architecture.md`.
It is a **multi-agent system**, not a single chatbot: an orchestrator delegates to specialized sub-agents (Investigator, Mitigation, Code-Fix, Communicator, Postmortem) that investigate alerts, take reversible mitigation actions, propose code fixes via PR, and write postmortems - against a self-contained **Target Service + Target Environment** it builds and controls (spec §2, §15), not real infra or a `modules/sandbox/` package.

## Repo structure - this is a uv workspace (Python's multi-module repo)

- `pyproject.toml` (root) - workspace definition only, not an installable package
  (`[tool.uv] package = false`). Declares `[tool.uv.workspace] members = ["modules/*"]` and the shared `[dependency-groups] dev = [...]` (pytest, ruff, mypy, nox, pre-commit).
- `modules/<name>/` - each is an **independent package**: own `pyproject.toml`, own version, own `src/<package_name>/`, own `tests/`. One shared `uv.lock` resolves third-party deps workspace-wide; each module's own version is independent and never auto-bumped by uv.
- `modules/argus_core/` - shared library (schemas, MCP transport, LLM client, logging, config). Other modules depend on it via `{ workspace = true }` in their `pyproject.toml`.
- **MCP servers are split by autonomy tier, not per integration** (spec §12.1): one read-only server and one write server, each paired with a typed client package (`*_mcp_server` / `*_mcp_client`). The server is a deployed process; the client is a library installed into calling agents, exposing each tool as a real typed function rather than a stringly-typed `call_tool(name, **kwargs)`. Shared transport lives once in `argus_core.mcp_transport`.
- `tests/` (repo root, outside `modules/`) - cross-module tests only:
  - `tests/integration/` - multiple modules interacting in-process
  - `tests/e2e/` - full stack via docker-compose, real chaos scenarios end-to-end
  - `tests/contract/` - verifies an agent's exposed tool schema still matches what the orchestrator expects to call (catches cross-module drift)
- `noxfile.py` - cross-module task runner. Sessions: `lint`, `typecheck`, `test_module` (parametrized per module, auto-discovered from `modules/*/pyproject.toml`), `test_all`, `contract`, `e2e`. Run `uv run nox --list` to see current sessions.

## How to run things
Always via `uv run ...` (uses the workspace `.venv`, no manual activation needed) or `uv run nox -s <session>`:

- `uv sync` - resolve workspace deps, create/update `.venv` and `uv.lock`
- `uv run nox -s lint` - ruff check, whole repo
- `uv run nox -s typecheck` - mypy, `modules/` only
- `uv run nox -s test_module -- <module-name>` - one module's unit and integration tests, isolated deps
- `uv run nox -s test_all` - every module's full test suite
- `uv run nox -s contract` - MCP tool-schema contract tests
- `uv run nox -s e2e` - brings up docker-compose stack, runs e2e and integration tests, tears down
  
## Conventions - follow these without being asked
- **TDD, with `tests/` off-limits to Claude.** The policy itself lives in `AGENTS.md` (tool-agnostic, applies to any AI coding agent, not just Claude). Mechanically enforced here via `.claude/settings.json` + a PreToolUse hook (`.claude/hooks/block_test_writes.py`) - Claude cannot create or edit files under any `tests/` directory. Claude may freely *read* and *run* existing tests (e.g. via `uv run nox -s test_module`). For the exact workflow to propose a new test, see the `tdd-new-behavior` skill.
- **Type hints on every function signature** (params and return type), matching mypy's expectations under `nox -s typecheck`. `-> None` for no return, not omitted.
- **Docstrings**: every nox session function gets a two-part docstring (what it registers as / how to invoke it, then what it actually does) - see the `nox-session-style` skill. Match this style for other non-trivial functions too (agents, tools, orchestrator FSM).
- **Ruff rule sets in play**: E, F, I, UP, B, SIM (see root `pyproject.toml`). Don't disable a rule inline without flagging it - ask first.
- **pytest markers**: tag every test with exactly one of `unit`, `integration`, `e2e`, `contract` (declared in root `pyproject.toml`). Don't add a new marker without updating that list.
- **`e2e`-marked tests only live in root `tests/e2e/`, never inside a module's own `modules/*/tests/`.** `nox -s test_module` filters to `unit or integration`, but `nox -s test_all` runs a module's tests unfiltered - if an `e2e` test ended up in a module's `tests/`, `test_all` would try to run it without docker-compose ever being brought up (only `nox -s e2e` does that, and only against root `tests/e2e/`). A module-level test needing the full stack belongs in root `tests/e2e/` instead. Enforced via `nox -s guard_e2e_boundary` / pre-commit.
- **Module boundaries**: don't reach into another module's `src/` directly - depend on it as a workspace package (`{ workspace = true }`) and import its public API only. If two agent modules need to share logic, that logic belongs in `modules/argus_core/`, not copy-pasted (or exposed via API).
- **Reversible vs. irreversible actions** (see spec §13): code that touches the sandbox's flag/deploy APIs must be tagged/logged as reversible mitigation. Anything resembling "merge a PR" or an infra apply must never be autonomous - always require explicit human approval in the code path, no exceptions, even in test/demo code.
- **No duplicate tool invocations across pre-commit and nox.** Before adding a new pre-commit hook, see the `pre-commit-hook-style` skill.
- **Test doubles: `unittest.mock` (`create_autospec`, `Mock(spec=...)`) is fine, `patch()` is not.** Dependencies get injected via a default-argument parameter (or, for 2+ related collaborators reused across calls, a constructor) - never via monkeypatching a module-level import. See the `test-mocking-style` skill for the full reasoning and known `create_autospec` gotchas before writing test doubles.

## Things NOT to do
- New modules are welcome and expected as the system grows - this rule is only about *how* to add one. Don't hardcode a module into `noxfile.py`'s module list; it's auto-discovered from `modules/*/pyproject.toml`. The way to add a module is `modules/<name>/pyproject.toml` (see the `new-module` skill) - nox picks it up automatically. If a module isn't showing up in `nox --list`, the fix is adding its `pyproject.toml`, not editing `noxfile.py`.
- Don't rename `pyproject.toml`, `uv.lock`, or `conftest.py` - these filenames are fixed by tooling convention, not configurable.
- Don't put per-tool config in separate files (`ruff.toml`, `pytest.ini`, etc.) unless asked - everything currently lives in the root `pyproject.toml` deliberately, as one scannable source of truth for the whole workspace.