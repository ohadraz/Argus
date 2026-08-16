---
name: nox-session-style
description: Use when adding or editing a nox session in noxfile.py, to keep session docstrings and structure consistent with the rest of the file.
---

Every `@nox.session` function gets:
- A type-hinted signature: `def <name>(session: nox.Session) -> None:` (add
  additional typed params if parametrized, e.g. `module: str`).
- A docstring with exactly two parts:
  1. First line(s): what it registers as and how to invoke it.
  2. Following line(s): what it actually does, factually - don't claim behavior
     the code doesn't have.
- Prefer `uv run <tool> ...` inside `session.run(..., external=True)` over calling
  a tool directly, so the session always uses the workspace's resolved environment.

**Teardown**: if a session brings up an external resource (docker-compose, a
container, a temp service, etc.), wrap setup + the work in `try` and put teardown
in `finally`, so the resource is always torn down even if a step fails. Never let
teardown be a plain sequential step after the risky one - that leaves resources
running on any failure.

**Fail-fast vs. continue-past-failures, for sessions looping over independent units** (e.g. one iteration per module): expose this via `session.posargs`, not a separate session name. Default (no posargs) is fail-fast - plain `try`/`except: raise` inside the loop, propagating the first failure immediately, for fast local iteration.
A recognized flag (e.g., `--ci` or `--aggregate`) switches to continue-past-failures: catch, record, keep looping, then call `session.error(...)` at the end summarizing every failure - for full-picture CI runs. Document both invocations in the docstring explicitly, including the exact flag name.

Before finalizing a new session's docstring, re-read the function body and confirm
every claim in the docstring is literally true of the code as written.
