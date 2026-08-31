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
  - `tests/contract/` - verifies a test double still matches the external party it stands in for (today: `anthropic_double` against the real Anthropic API)
- `noxfile.py` - cross-module task runner. Sessions: `lint`, `typecheck`, `test_module` (parametrized per module, auto-discovered from `modules/*/pyproject.toml`), `test_all`, `integration`, `contract`, `eval`, `e2e`. Run `uv run python -m nox --list` to see current sessions. Discovery skips the names in `EXCLUDED_FROM_TESTS` - currently `argus_testkit` and `anthropic_double`, both test-support code with no suite of their own.
- `modules/argus_testkit/` - shared test support (`Scenario`, `Assertion`, `all_of`, `eventually`), consumed as a **dev dependency** (`[dependency-groups] dev` + `[tool.uv.sources] ... { workspace = true }`), never a runtime one. It has no `tests/` directory and is excluded from test discovery. Off-limits to Claude, like `tests/` itself - propose changes in chat.
- `modules/anthropic_double/` - a record/replay stand-in for the Anthropic API (`POST /v1/messages` plus a `/double-control/*` seam), so the integration and contract suites exercise the real adapter with no key and no spend. Dev-only, in `EXCLUDED_FROM_TESTS`, no `argus_core` dependency. **Also off-limits to Claude** - it is the evidence the adapter is judged against, so propose changes in chat.

## How to run things
Always via `uv run ...` (uses the workspace `.venv`, no manual activation needed) or `uv run python -m nox -s <session>`:

- `uv sync --all-packages` - resolve workspace deps, create/update `.venv` and `uv.lock`. **Always `--all-packages`**: a bare `uv sync` (or `uv run` resolving on the fly) does not reliably install every workspace member's dependencies, and the symptom is spurious import errors out of `nox -s typecheck` that look like a code problem and are not.
- `uv run python -m nox -s lint` - ruff check, whole repo
- `uv run python -m nox -s typecheck` - mypy, `modules/` only
- `uv run python -m nox -s "test_module(module='<name>')"` - one module's unit and integration tests, isolated deps
- `uv run python -m nox -s test_all` - every module's full test suite
- `uv run python -m nox -s contract` - MCP tool-schema contract tests
- `uv run python -m nox -s e2e_replay` - the same stack and the same e2e tests, but `argus_web` points at the Anthropic double, so every model answer is replayed from a committed recording. Free, keyless, and what CI runs on every push. Proves the pipeline works; proves nothing about whether the model was right
- `uv run python -m nox -s e2e` - brings up docker-compose stack, runs e2e and integration tests, tears down. Reaches the **real** API and spends tokens - the manual pre-merge run

**Use `python -m nox`, not the bare `nox` shim** - Windows Smart App Control blocks the unsigned `.exe` stubs in `.venv/Scripts/`, and the block returns after every `uv sync`. When any tool here fails with *"An Application Control policy has blocked this file"* - failing to spawn, or failing to import - see the `smart-app-control-blocks` skill for which of the two fixes applies.
  
## Answering - this governs every reply, including mid-task ones

- **Two or three sentences by default.** If that is genuinely not enough, give
  the short answer first and offer to elaborate - do not pre-emptively elaborate.
- **A yes/no question gets `Yes` or `No` as the first word**, and often as the
  whole reply. Add at most one sentence, and only when a bare answer would leave
  the user unable to act.
- **If the question is not answerable as yes/no, say so** - "that isn't a yes/no
  question" - then offer either to answer at length or to have it rephrased.
  Do not quietly answer a different, easier question instead.
- **Asked for a number, a time, or a status: give it.** No formula, no
  derivation, no caveats unless the caveat changes the number.
- **Never restate what was already established** - no recaps of work just
  finished, no summaries of the plan, no repeating the user's own question back.
- Length is earned by the question, not by the size of the work behind it. A
  long investigation still gets a short answer.
- **Long-running jobs get unprompted progress** - anything on the scale of `e2e`,
  `e2e_replay`, `record` or a docker build. Report *how many of how many* have
  finished, elapsed time, and expected time to complete. A `Monitor` is the
  usual way; the mechanism is a free choice, the reporting is not. This is the
  one place where saying something unasked is wanted, and it stays one line.
- **Never pipe a backgrounded command through `Select-Object`/`head`/`tail`.**
  They buffer until the process exits, so the output file stays empty and there
  is nothing to report progress *from* - on exactly the long jobs the rule above
  is about. Run it raw, let the file fill live, and filter with `Grep`/`Read`
  when checking it. Same reason a truncated tail hides the real failure: read
  the whole log, narrow afterwards.

## Conventions - follow these without being asked
- **TDD, with `tests/`, `modules/argus_testkit/` and `modules/anthropic_double/` off-limits to Claude.** The policy itself lives in `AGENTS.md` (tool-agnostic, applies to any AI coding agent, not just Claude). Mechanically enforced here via `.claude/settings.json` + a PreToolUse hook (`.claude/hooks/block_test_writes.py`) - Claude cannot create or edit files under any `tests/` directory *in this repo*, nor anywhere in the shared test-support module or the Anthropic double. `Argus-Demo-Target-App` is outside that rule: it is a fixture, its tests are a regression net written after the code rather than a specification written before it, and Claude writes them directly there. Claude may freely *read* and *run* existing tests (e.g. via `uv run python -m nox -s test_module`). For the exact workflow to propose a new test, see the `tdd-new-behavior` skill. **Propose the entire file, never a fragment** - the human pastes it whole, and a set of "add this after line 40" instructions is how a test file quietly ends up not saying what either party thinks it says. Targeted edits only when tiny and precisely located.
- **Commit messages are a single line.** No body, no bullet list, no trailers. Draft the exact line, get approval on that line, then commit - see the `git-commit-approval` skill. Argus and `Argus-Demo-Target-App` are separate repos and commit separately.
- **Type hints on every function signature** (params and return type), matching mypy's expectations under `nox -s typecheck`. `-> None` for no return, not omitted.
- **Docstrings**: every nox session function gets a two-part docstring (what it registers as / how to invoke it, then what it actually does) - see the `nox-session-style` skill. Match this style for other non-trivial functions too (agents, tools, orchestrator FSM).
- **Ruff rule sets in play**: E, F, I, UP, B, SIM (see root `pyproject.toml`). Don't disable a rule inline without flagging it - ask first.
- **pytest markers**: tag every test with exactly one of `unit`, `integration`, `e2e`, `contract` (declared in root `pyproject.toml`). Don't add a new marker without updating that list.
- **`e2e`-marked tests only live in root `tests/e2e/`, never inside a module's own `modules/*/tests/`** (enforced via `nox -s guard_e2e_boundary` / pre-commit). See the `e2e-test-placement` skill for which directory and marker any given test belongs in.
- **Module boundaries**: don't reach into another module's `src/` directly - depend on it as a workspace package (`{ workspace = true }`) and import its public API only. If two agent modules need to share logic, that logic belongs in `modules/argus_core/`, not copy-pasted (or exposed via API).
- **Reversible vs. irreversible actions** (see spec §13): code that touches the sandbox's flag/deploy APIs must be tagged/logged as reversible mitigation. Anything resembling "merge a PR" or an infra apply must never be autonomous - always require explicit human approval in the code path, no exceptions, even in test/demo code.
- **No duplicate tool invocations across pre-commit and nox.** Before adding a new pre-commit hook, see the `pre-commit-hook-style` skill.
- **Private means private - across every boundary, tests included.** A leading `_` marks a name as belonging to its own module. Nothing outside that module may import or call it: not production code, not tests, not "just for testing". Python not enforcing this is not permission to ignore it. If a test needs to reach a `_name`, that is the design telling you the thing under test has no public seam - extract it into a module whose public API *is* the unit, and test that. Never widen a test's reach instead of widening the code's API.
- **Test variable naming: `some_` for arbitrary values, `dont_care_` for required-but-irrelevant ones, `a_`/`an_` for builders, no prefix when the value itself matters.** See the `test-naming-style` skill.
- **Repository method naming: bare `get()` only for primary-key lookups.** Anything relational - a lookup by foreign key, "the latest X for this Y" - gets a descriptive `get_*` name saying what it looks up by. `get()` with no qualifier is a promise that the argument is the identity.
- **`docs/spec-and-architecture.md` is a specification, not a changelog** - it describes the design as though it were always the intent. See the `spec-doc-style` skill before editing it.
- **Argus's own code is held to a high bar; `Argus-Demo-Target-App` is a fixture and is not.** Shortcuts are fine in the demo app and expected. A shortcut landing in Argus itself gets raised before it lands, not after.
- **A contract test needs a genuinely external party** - one that can change out from under you. `tests/contract/` is contract testing in Fowler's sense precisely because `anthropic_double` stands in for the Anthropic API: the tests check that a call against the double returns what a call to the real service would. **Argus's own components are not external to each other**, however many module boundaries sit between them - a cross-module seam changes only when this repo changes it, and a test asserting one module still matches another belongs in that module's own suite, not here.
- **Test doubles: `unittest.mock` (`create_autospec`, `Mock(spec=...)`) is fine, `patch()` is not.** Dependencies get injected via a default-argument parameter (or, for 2+ related collaborators reused across calls, a constructor) - never via monkeypatching a module-level import. See the `test-mocking-style` skill for the full reasoning and known `create_autospec` gotchas before writing test doubles.

## Things NOT to do
- New modules are welcome and expected as the system grows - this rule is only about *how* to add one. Don't hardcode a module into `noxfile.py`; it's auto-discovered from `modules/*/pyproject.toml`, so a module missing from `nox --list` needs its `pyproject.toml` written, not `noxfile.py` edited. See the `new-module` skill.
- Don't rename `pyproject.toml`, `uv.lock`, or `conftest.py` - these filenames are fixed by tooling convention, not configurable.
- Don't put per-tool config in separate files (`ruff.toml`, `pytest.ini`, etc.) unless asked - everything currently lives in the root `pyproject.toml` deliberately, as one scannable source of truth for the whole workspace.