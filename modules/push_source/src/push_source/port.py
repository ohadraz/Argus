"""Whoever tells Argus a repository moved, as the web application hears it.

Named for the role - a sender of pushes - and answered by one adapter named for
the code host that sends them. What crosses is what a push says in git's own
terms - the repository, the ref that moved, the commit it moved to - already
verified, never the host's payload or its signature scheme.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Pushed:
    """A ref that moved, as a verified delivery says it.

    `repository` is the repository as the host names it (`owner/name`), `ref`
    the ref that moved, in full as git names it (`refs/heads/main`, never the
    branch's name alone, so a tag of the same name is not taken for it), and
    `after` the commit it points at now.
    """

    repository: str
    ref: str
    after: str


class PushSource(Protocol):
    """A sender of pushes, for the one question the web application asks it."""

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Pushed | None:
        """What one delivery says, once its signature proves who sent it.

        Verified over the bytes that arrived before any of them is read:
        raises `PushUnverified` for a delivery the sender did not sign, or did
        not sign as it arrived. `None` for one that is verified and is no push -
        the host checking the address, or a delivery naming no commit.
        """
        ...
