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
- Prefer `uv run python -m <tool> ...` inside `session.run(..., external=True)` over
  calling a tool's console-script entry point directly (`uv run <tool> ...`, or the
  bare binary) - same resolved workspace environment either way, but going through
  the interpreter avoids Windows Smart App Control blocking the locally generated,
  unsigned console-script stub in `.venv/Scripts/` (observed blocking `nox.exe` and
  `uvicorn.exe`; the venv's `python.exe` itself isn't affected). Doesn't apply to
  non-Python binaries (e.g. `docker`) - only tools installed as Python console
  scripts. Same principle for any `subprocess.Popen`/direct-binary-path calls
  (e.g. a background process a session starts and later signals) - invoke the
  venv's `python.exe` with `-m <tool>` rather than that tool's own `.exe`.

**Teardown**: if a session brings up an external resource (docker-compose, a
container, a temp service, etc.), wrap setup + the work in `try` and put teardown
in `finally`, so the resource is always torn down even if a step fails. Never let
teardown be a plain sequential step after the risky one - that leaves resources
running on any failure.

**Fail-fast vs. continue-past-failures, for sessions looping over independent units** (e.g. one iteration per module): expose this via `session.posargs`, not a separate session name. Default (no posargs) is fail-fast - plain `try`/`except: raise` inside the loop, propagating the first failure immediately, for fast local iteration.
A recognized flag (e.g., `--ci` or `--aggregate`) switches to continue-past-failures: catch, record, keep looping, then call `session.error(...)` at the end summarizing every failure - for full-picture CI runs. Document both invocations in the docstring explicitly, including the exact flag name.

Before finalizing a new session's docstring, re-read the function body and confirm
every claim in the docstring is literally true of the code as written.
