"""Both code-host ports, answered from memory.

Built from a `RepositoryState` and changed by every write, so a write is read
back as the host would read it back. Everything it says is what the ports
promise and the ports' suite pins over both adapters - so what GitHub does that
the ports do not promise, it does not do either: no listing is ever cut short,
no rename or copy is told apart from a file that went and one that arrived, and
every file is text.

How two commits stand is read from history, as a host reads it, and never from
what they hold: two commits with the same files can be on different lines. A
comparison lists what the head changed since the two lines parted, as a host
lists one, and two commits with no common ancestor are refused - nothing the
suite holds says what a host answers for them.
"""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from code_host import (
    BranchNotWritten,
    ChangedFile,
    PullRequestNotOpened,
    Relation,
    RepositoryUnreadable,
    SourceDifference,
)
from core.models import OpenedPullRequest, RevisionSource

from code_host_double.state import RepositoryState

# A host's words for a file's change in a comparison - the three of its seven a
# content comparison can tell apart.
_ADDED: Final = "added"
_REMOVED: Final = "removed"
_MODIFIED: Final = "modified"

# Three lines of context around each change, as a host's patch has, and the
# two header lines a unified diff starts with, which a host's patch does not.
_CONTEXT_LINES: Final = 3
_FILE_HEADER_LINES: Final = 2

# Where a proposal is said to be readable: a host that does not resolve, so no
# address this double answers with leads anywhere.
_UNREACHABLE_PAGES: Final = "https://code-host.invalid"


@dataclass(frozen=True)
class Proposed:
    """One draft the host was asked to open, as it recorded it."""

    number: int
    head: str
    base: str
    title: str
    body: str
    draft: bool


class InMemoryCodeHost:
    """A code host held in memory, answering both ports.

    `repository` is the one repository it holds, as `owner/name`. `unreachable`
    builds a host nothing reaches, every call to which fails as its port says
    that call fails - a read as `RepositoryUnreadable`, a branch as
    `BranchNotWritten`, a proposal as `PullRequestNotOpened`.
    """

    def __init__(self,
                 state: RepositoryState,
                 *,
                 repository: str,
                 unreachable: bool = False) -> None:
        self._repository = repository
        self._trees = {commit.sha: dict(commit.files) for commit in state.commits}
        self._parents = {commit.sha: commit.parents for commit in state.commits}
        self._branches = dict(state.branches)
        self._proposed: list[Proposed] = []
        self._unreachable = unreachable

    @property
    def repository(self) -> str:
        return self._repository

    @property
    def proposed(self) -> tuple[Proposed, ...]:
        """Every draft opened, in the order they were opened."""
        return tuple(self._proposed)

    def files_at(self, ref: str, /) -> list[str]:
        return sorted(self._tree_at(ref))

    def file_at(self, path: str, ref: str, /) -> str:
        tree = self._tree_at(ref)

        if path not in tree:
            raise RepositoryUnreadable(f"no file [{path}] at [{ref}]")

        return tree[path]

    def source_at(self, ref: str, /) -> dict[str, str]:
        return dict(self._tree_at(ref))

    def difference_between(self, base: str, head: str, /) -> SourceDifference:
        """What `head` changed since the two lines parted; and, for a head not
        ahead, what `base` changed since then, each file read from `base`'s
        content to the merge base's - as `head` has it wherever it left the
        file alone - under the status that reading gives."""
        was, now, merge_base = self._compared(base, head)
        relation = self._relation(was, now)
        taken_away = (
            self._changes(self._trees[was], self._trees[merge_base],
                          among=self._paths_changed(merge_base, was))
            if relation in (Relation.BEHIND, Relation.DIVERGED) else ()
        )

        return SourceDifference(
            base=base,
            head=head,
            files=self._changes(self._trees[merge_base], self._trees[now],
                                among=self._paths_changed(merge_base, now)),
            more_files_than_listed=False,
            relation=relation,
            merge_base=merge_base,
            taken_away=taken_away
        )

    def paths_changed_between(self, base: str, head: str, /) -> list[str] | None:
        """Every path either side changed since the two lines parted - never
        `None`, since nothing here is ever cut short."""
        was, now, merge_base = self._compared(base, head)
        sides = [self._paths_changed(merge_base, now)]

        if self._relation(was, now) in (Relation.BEHIND, Relation.DIVERGED):
            sides.append(self._paths_changed(merge_base, was))

        return list(dict.fromkeys(path for side in sides for path in side))

    def head_of(self, branch: str, /) -> str:
        self._reached()

        if branch not in self._branches:
            raise RepositoryUnreadable(f"no branch [{branch}]")

        return self._branches[branch]

    def contains(self, branch: str, revision: str, /) -> bool:
        head = self.head_of(branch)

        return self._commit_of(revision) in self._history_of(head)

    def where_to_read(self,
                      repo_url: str,
                      revision: str,
                      path: str | None,
                      /) -> RevisionSource | None:
        """`None`: this host serves no pages, which is the port's answer for a
        host whose pages are not known."""
        return None

    def commit_to_new_branch(self,
                             branch: str,
                             base_commit: str,
                             files: Mapping[str, str],
                             message: str,
                             /) -> str:
        """One commit of the base's files with `files` over them, made on
        `base_commit`, and `branch` created pointing at it, last.

        Asked again with the same fix, the branch it already wrote is the
        answer. A branch holding any other files is somebody's work under the
        name, refused and left as it is.
        """
        if self._unreachable:
            raise BranchNotWritten("the host is not reachable")

        if base_commit not in self._trees:
            raise BranchNotWritten(f"no commit [{base_commit}] to write on")

        tree = {**self._trees[base_commit], **files}

        if branch in self._branches:
            if self._trees[self._branches[branch]] == tree:
                return branch

            raise BranchNotWritten(
                f"branch [{branch}] already exists, holding work this call did not write"
            )

        sha = hashlib.sha1(f"{base_commit}:{sorted(tree.items())}:{message}".encode()).hexdigest()
        self._trees[sha] = tree
        self._parents[sha] = (base_commit,)
        self._branches[branch] = sha

        return branch

    def propose(self, head: str, base: str, title: str, body: str, /) -> OpenedPullRequest:
        """A draft from `head` onto `base`, recorded - or, asked again, the one
        already open from `head` onto `base`. Refused where either is no
        branch."""
        if self._unreachable:
            raise PullRequestNotOpened("the host is not reachable")

        if head not in self._branches:
            raise PullRequestNotOpened(f"no branch [{head}] to propose from")

        if base not in self._branches:
            raise PullRequestNotOpened(f"no branch [{base}] to propose onto")

        opened = next((each for each in self._proposed if (each.head, each.base) == (head, base)),
                      None)

        if opened is None:
            opened = Proposed(number=len(self._proposed) + 1, head=head, base=base,
                              title=title, body=body, draft=True)
            self._proposed.append(opened)

        return OpenedPullRequest(
            number=opened.number,
            url=f"{_UNREACHABLE_PAGES}/{self._repository}/pull/{opened.number}",
            branch=head
        )

    def _compared(self, base: str, head: str) -> tuple[str, str, str]:
        """Both ends as commits, and where their lines part."""
        was = self._commit_of(base)
        now = self._commit_of(head)
        common = self._history_of(was) & self._history_of(now)
        nearest = sorted(
            commit for commit in common
            if not any(commit in self._history_of(other) for other in common - {commit})
        )

        if not nearest:
            raise RepositoryUnreadable(f"[{base}] and [{head}] have no common ancestor")

        return was, now, nearest[0]

    def _relation(self, was: str, now: str) -> Relation:
        if was == now:
            return Relation.IDENTICAL

        if was in self._history_of(now):
            return Relation.AHEAD

        if now in self._history_of(was):
            return Relation.BEHIND

        return Relation.DIVERGED

    def _paths_changed(self, since: str, to: str) -> list[str]:
        """Every path that differs between two commits' files, in path order."""
        was, now = self._trees[since], self._trees[to]

        return sorted(path for path in {*was, *now} if was.get(path) != now.get(path))

    def _changes(self,
                 was: Mapping[str, str],
                 now: Mapping[str, str],
                 *,
                 among: list[str]) -> tuple[ChangedFile, ...]:
        """Each of these paths as read from `was` to `now`."""
        return tuple(
            ChangedFile(
                path=path,
                status=(_ADDED if path not in was else
                        _REMOVED if path not in now else _MODIFIED),
                patch=_patch_between(was.get(path, ""), now.get(path, ""))
            )
            for path in among
        )

    def _tree_at(self, ref: str) -> dict[str, str]:
        return self._trees[self._commit_of(ref)]

    def _commit_of(self, ref: str) -> str:
        """The commit a branch points at, or the commit named - refused for
        anything else."""
        self._reached()
        commit = self._branches.get(ref, ref)

        if commit not in self._trees:
            raise RepositoryUnreadable(f"no branch or commit [{ref}]")

        return commit

    def _history_of(self, commit: str) -> set[str]:
        """The commit and every commit it reaches back through."""
        seen: set[str] = set()
        waiting = [commit]

        while waiting:
            each = waiting.pop()

            if each not in seen:
                seen.add(each)
                waiting.extend(self._parents.get(each, ()))

        return seen

    def _reached(self) -> None:
        if self._unreachable:
            raise RepositoryUnreadable("the host is not reachable")


def _patch_between(was: str, now: str) -> str:
    """The change as a host writes a patch: unified hunks with three lines of
    context, from the first `@@`."""
    lines = difflib.unified_diff(was.splitlines(), now.splitlines(),
                                 n=_CONTEXT_LINES, lineterm="")

    return "\n".join(list(lines)[_FILE_HEADER_LINES:])
