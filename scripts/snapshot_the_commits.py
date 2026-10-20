#!/usr/bin/env python3
"""
Stores, for every commit a scenario deploys, the files its real comparison lists.

A recording is captured against the real repository, and the walk it captures
reads a deployment's diff there - GitHub's patch, numbered from where each
change sits in its file and headed with the line above it. A replay reads the
GitHub double instead, which compares the two texts a case staged. Staged as
excerpts, every file starts at line one and the patch a replay reads is not the
patch its recording read; staged whole, as the commit holds them, the two agree.

So each commit's files are taken from the shop's own history rather than written
about it: every path `git diff` names between a pair's two commits, at each of
them, with `git show <sha>:<path>`. Run when a pair is added to
`tests/e2e/framework/deployments.py`:

    uv run python -m scripts.snapshot_the_commits

Byte for byte, and into one directory per commit named by its first seven
characters, each file under its repository path with `.txt` after it so nothing
here imports, lints or typechecks the shop's source. A commit cannot change, so
nothing stored is ever stale - which is why this only adds, and never clears.

`--into` writes somewhere else, for when the destination is not this script's
to write.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final

from tests.e2e.framework.deployments import COMMITTED, EVERY_PAIR, STORED_AS

HERE: Final = Path(__file__).resolve().parent.parent
THE_SHOP: Final = HERE.parent / "Argus-Demo-Target-App"


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(THE_SHOP), *arguments], capture_output=True, check=True
    ).stdout


def the_paths_changed(before: str, after: str) -> list[str]:
    """Every path the comparison of the two commits lists, as GitHub lists it."""
    return _git("diff", "--name-only", before, after).decode().split()


def the_file_at(sha: str, path: str) -> bytes | None:
    """The file as the commit holds it, or `None` where the commit has none."""
    try:
        return _git("show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--into", type=Path, default=COMMITTED)
    into: Path = parser.parse_args().into

    if not (THE_SHOP / ".git").exists():
        print(
            f"The shop is not beside this repository: no checkout at [{THE_SHOP}]. "
            f"Nothing was written.",
            file=sys.stderr
        )
        sys.exit(1)

    for pair in EVERY_PAIR:
        for sha in (pair.before, pair.after):
            for path in the_paths_changed(pair.before, pair.after):
                held = the_file_at(sha, path)

                if held is None:
                    continue

                stored = into / sha[:7] / f"{path}{STORED_AS}"
                stored.parent.mkdir(parents=True, exist_ok=True)
                stored.write_bytes(held)
                print(f"  {sha[:7]} {path}")


if __name__ == "__main__":
    main()
