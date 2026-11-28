"""What a code host holds before anybody asks it anything.

The seed both adapters in the ports' suite are built from: the double reads it
directly, and the suite stages it in `github_double` through that double's own
surfaces. Every value is frozen and every collection a tuple, so a seed is the
same seed whoever holds it and however many hosts are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeldCommit:
    """One commit: its sha, every file it holds and what each says, and the
    commits it was made on.

    The files are the commit's whole tree, as a commit holds one: a path not
    among them is not in the repository at this commit. `parents` is its
    history, which is what says how two commits stand - never what they hold.
    """

    sha: str
    files: tuple[tuple[str, str], ...]
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryState:
    """Everything the repository holds: its commits, and each branch with the
    commit it points at."""

    commits: tuple[HeldCommit, ...]
    branches: tuple[tuple[str, str], ...] = ()
