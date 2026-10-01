---
name: smart-app-control-blocks
description: Use when a tool on this Windows machine dies with "An Application Control policy has blocked this file" - failing to spawn (os error 4551, e.g. nox.exe) or failing to import (ImportError: DLL load failed, e.g. mypy, librt, xxhash).
---

Smart App Control is enforcing here. In enforcement it runs Microsoft's
`VerifiedAndReputableDesktop` policy, which admits a binary that is **signed by a
trusted-root CA** or that **Microsoft's reputation service already knows**. Most
Python native extensions are neither: almost nothing on PyPI signs its `.pyd`
files, so what usually decides is reputation - and reputation is a verdict about
one exact file, looked up over the network, that can change without anything on
disk changing.

So a wheel downloaded from PyPI is **not** automatically fine. That is the
correction: this file used to say SAC judges only binaries built on this machine,
and that cost a session a wrong diagnosis. Unsigned extensions inside official
wheels are blocked routinely elsewhere too - PyAV's `logging.pyd` (closed as not
planned), `aws-cli`'s `_awscrt.pyd`, `qiskit-ibm-runtime`'s `sspilib`, grimp's
`_rustgrimp`.

## Try the upgrade first

**A different version is a different file, so it gets its own verdict.** This is
the cheapest fix and it has worked:

```
uv lock --upgrade-package <name>
uv sync --all-packages
```

On 2026-10-01 `xxhash 4.0.0`'s published `cp314-win_amd64` wheel was blocked
mid-session - it had imported fine an hour earlier, and nothing had been rebuilt,
so what moved was the reputation verdict. `xxhash 4.0.1` imports and the whole
suite runs on Windows. Upgrading a transitive dependency is allowed here;
**pinning or downgrading one is not**, so do not reach for an older release that
happens to be better known.

A block that appears with no install having happened is this shape. Suspect
reputation, not your tree.

## What not to reach for

**`no-binary-package` is almost always the wrong answer, and is how this once
went wrong.** It means "never take the wheel", which for a package carrying C
means "compile it here" - manufacturing a brand-new unsigned binary with no
reputation at all, which is worse than the one that was refused. This repo carried
`no-binary-package = ["mypy", "librt"]` and that line *was* the blocked `librt`.
Removing it fixed everything.

It helps only where the sdist is pure Python.

**Reinstalling to "refresh" a blocked package makes it worse**, for the same
reason: the build it produces is newer and less known than what is already there.

**There is no per-file exception.** SAC cannot be told to allow one import, so
"how do I approve it" has no answer. And turning SAC off is a one-way door on a
machine - it cannot be switched back on without reinstalling Windows - so it is
the user's call and never a step to take while fixing something else.

## Two shapes

`ImportError: DLL load failed while importing <name>` - the block is inside the
package, so `python -m <tool>` does not help. **Read the traceback for which
package is actually blocked**: mypy 2.x keeps part of itself in `librt`, and
`langsmith` reaches `xxhash` through `run_trees`, so both fail several lines below
anything naming the thing you invoked.

A pytest plugin is worth a second look here. `langsmith` registers one that pytest
auto-loads, which dragged `xxhash` into collection for *every* suite; the root
`pyproject.toml` now carries `addopts = "-p no:langsmith_plugin"`, which declines
a plugin nothing wanted. That only helps where the import is the plugin's -
`orchestrator` imports LangGraph for real, so the flag did nothing for it and the
upgrade is what fixed it.

`Failed to spawn ... (os error 4551)` - a `.venv/Scripts/*.exe` stub uv generated
locally. `uv run python -m nox ...` skips the stub. Cheap insurance; the stubs
currently spawn fine.

## One trap

**uv's "no usable wheels" does not mean the release has none.**
`no-binary-package` excludes every wheel and `--only-binary` excludes every source
build; together they leave nothing, and uv reports it as though PyPI were empty.
Check the release's files before concluding anything - `pypi.org/pypi/<name>/json`
lists them, and it is also how to see whether a newer version exists to upgrade
to.

## When the upgrade does not help

Run that step in WSL, in an environment of its own (`.venv/` holds Windows
binaries):

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/argus-typecheck-venv"
cd /mnt/c/Users/ohadr/Projects/Argus && uv sync --all-packages
uv run --all-packages python -m mypy modules tests
```

This is the fallback, not the first move. Reach for it once an upgrade has been
tried and the traceback has been read for which package is really blocked.
