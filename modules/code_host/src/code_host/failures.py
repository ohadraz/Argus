"""How the code host fails to do what was asked, in three kinds.

One for every read, because a caller's next move is the same however a read
failed: it does not know what the code says. And one for each of the two
writes, because they fail differently and a caller has to tell them apart - a
branch that was never written leaves nothing to propose, and a proposal that was
never made leaves a fix on a branch nobody was sent to.
"""

from __future__ import annotations


class RepositoryUnreadable(Exception):
    """The source could not be read, whatever the reason.

    One exception for an unreachable host, a rejected credential, a path that is
    not there, a listing the host cut short and an archive that will not open,
    because the caller's next move is the same for all of them: it does not
    know what the code says. Each has an innocent-looking empty answer available
    - no files, no matches, nothing to index - and every one of those would be
    read as a fact about the repository rather than about the attempt to read
    it.
    """


class BranchNotWritten(Exception):
    """The fix is not on a branch, whatever the reason.

    One exception for an unreachable host, a rejected credential, a branch that
    already existed and a write the repository refused - because the caller's
    next move is the same for all four: there is nothing to open a pull request
    from, so it must not open one.

    Anything it is raised for leaves no branch behind. Everything written before
    the ref is an object nothing points at, which is a repository's own business
    to collect - so a failure partway through is not a half-finished branch for
    somebody to find, it is a branch that was never created.
    """


class PullRequestNotOpened(Exception):
    """No pull request exists, whatever the reason.

    One exception for an unreachable host, a rejected credential, a repository
    that refused the branch and an answer with no pull request in it, because
    the caller's next move is the same for all four: there is nothing to send a
    human to. A proposal reported optimistically would close an incident on a
    link to nothing, which is worse than one that failed loudly - the fix is
    still missing either way, and only one of them says so.
    """
