"""The code host, held in memory: a double of the port, for suites.

A second adapter of `code_host`'s ports, and never one a process runs: a fix
proposed in memory would have Argus report a proposal nobody can open, so it
lives where nothing that ships can install it. It is held to the ports by
their own suite, which runs it beside the vendor's adapter over one seed and
asks both the same questions.

`RepositoryState` is the seed - the commits, each with its files and the
commits it was made on, and where each branch points - and `InMemoryCodeHost`
answers both ports from it, each write changing what the reads then answer.
What it was asked to propose is kept as `Proposed`, for a suite to read back.
"""

from __future__ import annotations

from code_host_double.in_memory import InMemoryCodeHost, Proposed
from code_host_double.state import HeldCommit, RepositoryState

__all__ = [
    "HeldCommit",
    "InMemoryCodeHost",
    "Proposed",
    "RepositoryState"
]
