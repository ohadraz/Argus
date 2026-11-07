#!/usr/bin/env python3
"""
Stores, for every commit a scenario deploys, the files a walk reads at it.

A recording is captured against the real repository, and the walk it captures
reads a deployment's diff there - GitHub's patch, numbered from where each
change sits in its file and headed with the line above it. A replay reads the
GitHub double instead, which compares the two texts a case staged. Staged as
excerpts, every file starts at line one and the patch a replay reads is not the
patch its recording read; staged whole, as the commit holds them, the two agree.

Two kinds of file, and nothing else, because nothing else is read. Every path
the pair changes, so the comparison names what GitHub's named. And each path in
the pair's `also_read`: the files Code-Fix's reading names, and the ones holding
a use of what its patch changes, are read again at the revision that ran, and a
staged commit holds only what the case staged - so a file left out is a 404 in
the replay where its recording, reading GitHub, read it. Both kinds at both
commits: the comparison reads the two staged trees whole, and a file staged at
one only would be named as added.

So each commit's files are taken from the shop's own history rather than written
about it: each of those paths `git ls-tree` finds at the commit, with
`git show <sha>:<path>`. Run when a pair is added to
`tests/e2e/framework/deployments.py`, or its `also_read` grows:

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

from scripts.snapshot_the_shop import THE_SHOP
from tests.e2e.framework.deployments import COMMITTED, EVERY_PAIR, STORED_AS


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(THE_SHOP), *arguments], capture_output=True, check=True
    ).stdout


def the_paths_changed(before: str, after: str) -> list[str]:
    """Every path that differs between the pair's two commits."""
    return _git("diff", "--name-only", before, after).decode().splitlines()


def the_paths_held(sha: str, wanted: list[str]) -> list[str]:
    """Each of `wanted` the commit holds - none where nothing is wanted, since
    `ls-tree` given no path names every file."""
    if not wanted:
        return []

    return _git("ls-tree", "-r", "--name-only", sha, "--", *wanted).decode().splitlines()


def the_file_at(sha: str, path: str) -> bytes:
    """The file as the commit holds it."""
    return _git("show", f"{sha}:{path}")


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
        wanted = [*the_paths_changed(pair.before, pair.after), *pair.also_read]

        for sha in (pair.before, pair.after):
            for path in the_paths_held(sha, wanted):
                stored = into / sha[:7] / f"{path}{STORED_AS}"
                stored.parent.mkdir(parents=True, exist_ok=True)
                stored.write_bytes(the_file_at(sha, path))

            print(f"  {sha[:7]}")


if __name__ == "__main__":
    main()
