---
name: smart-app-control-blocks
description: Use when a tool on this Windows machine dies with "An Application Control policy has blocked this file" - failing to spawn (os error 4551, e.g. nox.exe) or failing to import (ImportError: DLL load failed, e.g. mypy, librt).
---

Smart App Control is enforcing here. What it judges is **a binary built on this
machine**. A wheel downloaded from PyPI is fine, compiled or not.

So when an import is blocked, ask *what built this file here* - not *how do I
approve it*, because there is no approving one by hand.

**`no-binary-package` is almost always the wrong answer, and is how this last
went wrong.** It means "never take the wheel", which for a package carrying C
means "compile it here" - manufacturing the exact file SAC refuses. This repo
carried `no-binary-package = ["mypy", "librt"]` and that line *was* the blocked
`librt`. Removing it fixed everything; both packages now install as published
wheels and type checking runs with SAC untouched.

It helps only where the sdist is pure Python, and only once you have confirmed
the published wheel is genuinely refused.

## Two shapes

`ImportError: DLL load failed while importing internal` - the block is inside
the package, so `python -m <tool>` does not help. **Read the traceback for which
package is blocked**: mypy 2.x keeps part of itself in `librt`, which fails a
line further down than anything naming mypy.

`Failed to spawn ... (os error 4551)` - a `.venv/Scripts/*.exe` stub uv
generated locally. `uv run python -m nox ...` skips the stub. Cheap insurance;
the stubs currently spawn fine.

Neither shape reproduces on this machine as of 2026-09-14, with SAC enforcing
and no workaround in `pyproject.toml`.

## Two traps

**uv's "no usable wheels" does not mean the release has none.**
`no-binary-package` excludes every wheel and `--only-binary` excludes every
source build; together they leave nothing, and uv reports it as though PyPI were
empty. Check the release's files before concluding anything.

**Reinstalling to "refresh" a blocked package makes it worse**, since the build
it produces is newer and less known than the one already there.

If a genuinely unpublished binary is ever blocked, run that step in WSL, in an
environment of its own (`.venv/` holds Windows binaries):

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/argus-typecheck-venv"
cd /mnt/c/Users/ohadr/Projects/Argus && uv sync --all-packages
uv run --all-packages python -m mypy modules tests
```
