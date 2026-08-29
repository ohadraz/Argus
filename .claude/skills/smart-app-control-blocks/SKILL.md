---
name: smart-app-control-blocks
description: Use when a tool on this Windows machine dies with "An Application Control policy has blocked this file" - either failing to spawn (os error 4551, e.g. nox.exe, uvicorn.exe) or failing to import (ImportError: DLL load failed, e.g. mypy). Explains which of the two fixes applies and why clearing the block by hand does not last.
---

Windows Smart App Control blocks locally installed, unsigned binaries in
`.venv/`. It shows up in two shapes, with two different fixes. Read the error
before choosing: **spawn** failures and **import** failures are not the same
problem.

## Shape 1: a console-script shim will not spawn

```
Failed to spawn: nox ... An Application Control policy has blocked this file (os error 4551)
```

`.venv/Scripts/<tool>.exe` is a stub uv generates locally, so it is unsigned and
gets blocked. The interpreter itself is signed and is not.

**Fix: go through the interpreter.** `uv run python -m nox ...`, never the bare
`nox`. Same code, same environment, no stub. This is why every nox invocation in
this repo is written `uv run python -m nox -s <session>`, and why `noxfile.py`
runs tools as `python -m <tool>` inside `session.run(...)`.

Every `uv sync` that touches the environment rewrites those stubs, so clearing
the block by hand comes back. Don't bother.

Doesn't apply to non-Python binaries - `docker` is signed and fine.

## Shape 2: the package's own modules are compiled

```
ImportError: DLL load failed while importing internal: An Application Control policy has blocked this file.
```

Here the block is *inside* the package, not on a wrapper around it, so `python -m
<tool>` fails exactly as `<tool>.exe` would - `mypy --version` fails too.

**Fix: install it from source.** In the root `pyproject.toml`:

```toml
[tool.uv]
no-binary-package = ["mypy", "librt"]
```

That builds the pure-Python wheel from the sdist: same tool, several times
slower, and it survives `uv sync` - which hand-clearing does not. Apply with
`uv sync --all-packages --reinstall-package <name>`, then confirm with
`uv run python -m mypy --version`, which prints `(compiled: no)` when it worked.

**Read the traceback for which package is actually blocked - it need not be the
one you invoked.** `librt` is listed beside `mypy` for exactly this reason: mypy
2.x moved part of its machinery into that separate package, which ships compiled
too, so a pure-Python mypy alone still imports a blocked `.pyd` and fails
identically, one line further down the traceback. A fix that names only the
top-level tool will look like it did nothing.

## Which fix

| The error says | The block is on | Fix |
|---|---|---|
| failed to spawn / os error 4551 | the `.exe` stub | `python -m <tool>` |
| `ImportError: DLL load failed` | a `.pyd` inside the package | `no-binary-package` |
