"""What Argus asks of whatever hosts the Target Service's repository.

Split where the MCP servers are split (spec §12.1): one port that can only read
the repository, and one that can only put a proposed fix on a branch of its own
and propose it. The read server and the index are handed the first, so a write
typed there does not type-check; the write server the second, so a read typed
there does not either - and the line the two servers draw holds in the code
they run as well as in the processes they run in.

Every operation is named for what Argus wants rather than for the route that
answers it, and every answer is Argus's own value. Nothing here is a URL, a
token, a media type or an archive's layout; those are an adapter's, and an
adapter is named for its vendor.

There is no merge, and there will not be one. Merging is a deploy, and no
deploy is among the actions Argus may take unasked (§13): the port cannot say
it, so no adapter can be asked it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from core.models import OpenedPullRequest, RevisionSource


class Relation(StrEnum):
    """How the head of a comparison stands to its base, in git's words.

    Past it, the same commit, short of it, or on another line from it. The first
    two put the base in the head's history.
    """

    AHEAD = "ahead"
    IDENTICAL = "identical"
    BEHIND = "behind"
    DIVERGED = "diverged"


@dataclass(frozen=True)
class ChangedFile:
    """One file a comparison names, and what happened inside it.

    `patch` is optional because the host omits it rather than sending an empty
    one: a file that is not text has no diff to show, and a diff the host judges
    too large is left out with every other field present. An empty string would
    say the file was touched and nothing happened to it, which is a different
    fact and one a reader counting changed source would count the wrong way.

    `previous_path` is set only on a rename, and is the half of a rename a reader
    otherwise never learns. Named only by where it went, a file that moved is
    indistinguishable from one that appeared - and the two say different things
    about what a deployment did.

    `status` is carried as the host spelled it, and turned round only where the
    file is read in the other direction (`taken_away`). A vocabulary of this
    port's own would be a second spelling for a reader to learn for no gain.
    """

    path: str
    status: str
    patch: str | None = None
    previous_path: str | None = None
    # Where a copy the other side made was copied from, on the file the deploy
    # removed for not having it - which carries no patch, since the comparison
    # shows only how the copy differed from its source. Set there alone.
    copied_from: str | None = None


@dataclass(frozen=True)
class SourceDifference:
    """Everything that differs between two commits, as far as it could be listed.

    Carries the two revisions it is a difference of, because what reads it is a
    model rather than the caller that asked: a diff that does not say what it is a
    diff of is one the reader has to trust it was handed correctly.

    `more_files_than_listed` is the flag that keeps a cut-off answer from reading
    as a complete one. A short list is what both look like, and a deployment that
    rewrote a repository would otherwise arrive as one that touched the handful of
    files that happened to fit.

    `relation` is how `head` stands to `base`, and `merge_base` where their lines
    of history part. `files` is what `head` changed since then - which, for a
    head not ahead of its base, is not all of what differs: `taken_away` is what
    `base` had changed since then and `head` does not have, each read as going
    from `base` to `head`, so every patch in the difference reads in one
    direction. Empty where `head` is ahead, since it then has all of it.
    """

    base: str
    head: str
    files: tuple[ChangedFile, ...]
    more_files_than_listed: bool
    relation: Relation | None = None
    merge_base: str | None = None
    taken_away: tuple[ChangedFile, ...] = ()


class CodeHostReads(Protocol):
    """The repository read, and nothing that could change it.

    Every read raises `RepositoryUnreadable` rather than answering emptily. A
    repository that could not be reached, a path that is not there and a
    listing the host gave up on are the same thing to a caller: it does not
    know what the code says, and each has an innocent-looking empty answer -
    no files, no matches, nothing changed - that would be read as a fact about
    the repository rather than about the attempt to read it.
    """

    @property
    def repository(self) -> str:
        """The repository, as `owner/name` - what the index's record of it is
        kept under."""
        ...

    def files_at(self, ref: str, /) -> list[str]:
        """Every file in the repository at `ref`, as paths from its root -
        directories left out, and a listing the host cut short refused."""
        ...

    def file_at(self, path: str, ref: str, /) -> str:
        """What one file says at `ref`, as text - refused for a path that is
        not there and for a file that is not text."""
        ...

    def source_at(self, ref: str, /) -> dict[str, str]:
        """Every readable file at `ref`, keyed by its path from the root; a
        file that is not text is passed over rather than refused."""
        ...

    def difference_between(self, base: str, head: str, /) -> SourceDifference:
        """Every file that differs between the two commits, and what changed in
        each - in that order, since reversed it describes undoing the change."""
        ...

    def paths_changed_between(self, base: str, head: str, /) -> list[str] | None:
        """Every path that differs between the two commits, or `None` for "I
        cannot say" - a listing at the host's ceiling is not a complete one."""
        ...

    def head_of(self, branch: str, /) -> str:
        """The commit `branch` points at."""
        ...

    def contains(self, branch: str, revision: str, /) -> bool:
        """Whether `revision` is in `branch`'s history."""
        ...

    def where_to_read(self,
                      repo_url: str,
                      revision: str,
                      path: str | None,
                      /) -> RevisionSource | None:
        """The pages a person opens a deployed revision at - the repository a
        deployment platform names by `repo_url`, the commit, its files, and the
        directory - or `None` for a repository on a host whose pages are not
        known. Reads nothing: an address is worked out, not asked for."""
        ...


class CodeHostWrites(Protocol):
    """What proposing a fix can ask, and nothing else.

    Not the reads port as well: the write tier reads nothing of the repository
    but what a write needs to know - where the base points, whether its branch
    or proposal already landed - and that is the adapter's own business. A
    write port that also read would put a read under the token that pushes,
    which is the credential the tier split keeps out of every read.

    Both writes are safe to ask again. A call whose answer was lost on its way
    back is asked a second time over a new session, by which point the first
    may have landed - so a branch already holding the tree this call writes, or
    a draft already open from the branch onto the base, is the answer rather
    than a refusal. A branch holding anything else is somebody's work under
    the name, and is refused and left as it is.
    """

    def commit_to_new_branch(self,
                             branch: str,
                             base: str,
                             files: Mapping[str, str],
                             message: str,
                             /) -> str:
        """Commits `files` - each path's whole new content - as one change cut
        from `base`'s head, and creates `branch` pointing at it, last. Returns
        the branch.

        Raises `BranchNotWritten`; a failure leaves no branch behind.
        """
        ...

    def propose(self, head: str, base: str, title: str, body: str, /) -> OpenedPullRequest:
        """Proposes `head` onto `base` as a draft. Always a draft: there is no
        parameter that makes it anything else.

        Raises `PullRequestNotOpened` unless the host answered with a proposal
        that can be read back.
        """
        ...
