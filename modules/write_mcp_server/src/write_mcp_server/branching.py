"""Putting a proposed fix on a branch of its own (spec §7.4, §13).

The half of Code-Fix's outward act that touches code, and it touches only a
branch. Nothing here can write to `main`: the only ref this module ever writes
is a new one, so the worst a wrong patch can do is exist somewhere nobody is
running. What makes that change is a human merging it, which is not something
this server can do (see `pull_requests`).

The fix arrives as **one commit**, built the way git itself builds one: a tree
written over the base's tree, a commit pointing at that tree, and only then a
ref pointing at the commit. Writing file by file through the Contents API would
be simpler to read and wrong in two ways - it makes a commit per file, so a
reviewer gets three identical messages instead of one change, and it publishes
each file as it goes, so a patch that fails halfway is left on a branch looking
whole. A tree and a commit are unreachable objects until the last call, which is
what makes the branch appear complete or not at all.

Separate from opening the pull request because the two fail differently and a
caller needs to tell them apart - a push that was rejected and a proposal that
was never made are different situations, and a module doing both would report
them through one exception.

**No path here is off-limits, tests included.** A fix that arrives with the test
exposing the bug is the fix a person can trust, and that test belongs wherever
the service's tests live - so a tier second-guessing which files a patch may
touch would be refusing the most valuable half of it. What keeps a bad change
out is not this module's opinion of a path: it is that everything lands on a
branch nobody runs, and that merging is a person's act (§13).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

import httpx

from write_mcp_server.pull_requests import RepositoryWriteSettings

HttpGet = Callable[..., httpx.Response]
HttpPost = Callable[..., httpx.Response]

REQUEST_TIMEOUT_SECONDS = 10.0

# GitHub's wire vocabulary, named for the fields that carry it. `SHA_FIELD` is
# the same spelling for four different things and that is the API's doing, not
# ours - the commit a ref points at, the tree a commit points at, the tree a new
# one is written over, and the object each answer identifies itself by.
REF_FIELD: Final = "ref"
OBJECT_FIELD: Final = "object"
SHA_FIELD: Final = "sha"
MESSAGE_FIELD: Final = "message"
CONTENT_FIELD: Final = "content"
TREE_FIELD: Final = "tree"
BASE_TREE_FIELD: Final = "base_tree"
PARENTS_FIELD: Final = "parents"
PATH_FIELD: Final = "path"
MODE_FIELD: Final = "mode"
TYPE_FIELD: Final = "type"

# A tree entry says what kind of thing it is and what permissions it carries.
# Everything a fix writes is an ordinary, non-executable file: `100755` would
# hand a patch the ability to mark a file runnable, and `blob` is what
# distinguishes a file from a subdirectory or a submodule.
FILE_MODE: Final = "100644"
FILE_TYPE: Final = "blob"

ACCEPT_HEADER: Final = "application/vnd.github+json"


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


def commit_to_new_branch(branch: str,
                         base_branch: str,
                         files: Mapping[str, str],
                         message: str,
                         settings: RepositoryWriteSettings,
                         get: HttpGet = httpx.get,
                         post: HttpPost = httpx.post) -> str:
    """Commits `files` as one change and creates `branch` pointing at it.

    `files` maps a repository path to that file's **whole** new content, not to
    a diff. A patch is applied by the model that wrote it, not here: applying a
    diff is a second thing that can fail, and it fails by producing a file that
    is subtly not what anyone intended rather than by raising.

    Returns the branch it wrote, so the caller can hand it straight to
    `open_pull_request` without re-deriving a name that has to match.

    Every path the fix names is written, tests included: a patch that brings the
    test exposing the bug is the one worth reading, and refusing it a path would
    refuse exactly that.

    Raises `BranchNotWritten` if the repository refuses any step. The branch is
    the last thing written, so a failure means there is no branch rather than a
    branch with half a fix on it.
    """
    base_head = _head_of(base_branch, settings, get)
    base_tree = _tree_of(base_head, settings, get)

    tree = _write_tree(files, base_tree, settings, post)
    commit = _write_commit(tree, base_head, message, settings, post)

    _create_branch(branch, commit, settings, post)

    return branch


def _head_of(base_branch: str,
             settings: RepositoryWriteSettings,
             get: HttpGet) -> str:
    """The commit `base_branch` currently points at.

    The fix is cut from here so that it applies to the code that is actually
    deployed. A branch taken from anywhere else proposes a change against a
    repository nobody is running, and would merge cleanly into a fault that had
    already moved.
    """
    url = f"{_repository(settings)}/git/ref/heads/{base_branch}"

    try:
        response = get(url, headers=_headers(settings), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        head = answered[OBJECT_FIELD][SHA_FIELD]
    except Exception as error:
        raise BranchNotWritten(
            f"could not read the head of [{base_branch}] at [{url}]: {error}"
        ) from error

    return str(head)


def _tree_of(commit: str,
             settings: RepositoryWriteSettings,
             get: HttpGet) -> str:
    """The tree the base commit points at, which the fix is written over.

    Read rather than assumed, because a new tree must be written over a *tree*
    and what the ref gives back is a *commit*. Written over nothing instead, the
    fix would propose a repository containing only the files it touched - every
    other file in the service deleted, in a patch that reads as a small one.
    """
    url = f"{_repository(settings)}/git/commits/{commit}"

    try:
        response = get(url, headers=_headers(settings), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        tree = answered[TREE_FIELD][SHA_FIELD]
    except Exception as error:
        raise BranchNotWritten(
            f"could not read the tree of commit [{commit}] at [{url}]: {error}"
        ) from error

    return str(tree)


def _write_tree(files: Mapping[str, str],
                base_tree: str,
                settings: RepositoryWriteSettings,
                post: HttpPost) -> str:
    """The whole fix as one tree, written over the base's.

    Each entry carries its content directly rather than a blob written in a call
    of its own: the API writes the blob and uses its sha, which makes the number
    of requests a property of the fix being one change rather than of how many
    files it happens to touch.

    Over the base tree, so that everything the fix did not name stays where it
    was - this describes a repository, not a patch, and a tree written from
    nothing would describe one with nothing else in it.
    """
    url = f"{_repository(settings)}/git/trees"
    entries = [
        {
            PATH_FIELD: path,
            MODE_FIELD: FILE_MODE,
            TYPE_FIELD: FILE_TYPE,
            CONTENT_FIELD: content
        }
        for path, content in files.items()
    ]

    return _written(
        url,
        {BASE_TREE_FIELD: base_tree, TREE_FIELD: entries},
        f"could not write a tree over [{base_tree}]",
        settings,
        post
    )


def _write_commit(tree: str,
                  parent: str,
                  message: str,
                  settings: RepositoryWriteSettings,
                  post: HttpPost) -> str:
    """The one commit the fix arrives as.

    Its parent is the base's head, which is what makes it a change *to* that
    branch rather than an unrelated history: a commit written without one is a
    root commit, and a pull request from it has nothing to diff against.
    """
    url = f"{_repository(settings)}/git/commits"

    return _written(
        url,
        {MESSAGE_FIELD: message, TREE_FIELD: tree, PARENTS_FIELD: [parent]},
        f"could not commit tree [{tree}] onto [{parent}]",
        settings,
        post
    )


def _written(url: str,
             body: dict[str, Any],
             refused: str,
             settings: RepositoryWriteSettings,
             post: HttpPost) -> str:
    """Writes one git object and returns the sha the repository gave it.

    A tree and a commit are written the same way and read back the same way, and
    both are useless without the sha - there is nothing to point the next call
    at - so the failure and the extraction are said once rather than twice.
    """
    try:
        response = post(
            url,
            headers=_headers(settings),
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        written = answered[SHA_FIELD]
    except Exception as error:
        raise BranchNotWritten(f"{refused}: {error}") from error

    return str(written)


def _create_branch(branch: str,
                   at: str,
                   settings: RepositoryWriteSettings,
                   post: HttpPost) -> None:
    """Points a new branch at the finished commit - the last thing written.

    Until this call nothing in the repository refers to the fix at all. That
    ordering is the module's safety: `main` is never a ref this writes, and a
    branch either names a whole commit or was never created.
    """
    url = f"{_repository(settings)}/git/refs"

    try:
        response = post(
            url,
            headers=_headers(settings),
            json={REF_FIELD: f"refs/heads/{branch}", SHA_FIELD: at},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise BranchNotWritten(
            f"could not create branch [{branch}] at [{at}]: {error}"
        ) from error


def _repository(settings: RepositoryWriteSettings) -> str:
    return f"{settings.github_api_url}/repos/{settings.github_repository}"


def _headers(settings: RepositoryWriteSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": ACCEPT_HEADER
    }
