"""Putting a proposed fix on a branch of its own (spec §7.4, §13).

The half of Code-Fix's outward act that touches code, and it touches only a
branch. Nothing here can write to `main`: the only ref this module ever writes
is a new one, so the worst a wrong patch can do is exist somewhere nobody is
running. What makes that change is a human merging it, which is not something
this adapter can be asked (see `pull_requests`).

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

It can be asked twice: a call whose answer was lost on its way back to the walk
is asked again over a new session, and by then the branch may be there. So the
branch is looked for before it is created, and told apart by the tree it holds
- the fix already written, or somebody else's work under the name, left alone.
The fix is written over a commit it is handed, not over wherever a branch
points when it is asked, so every asking of one fix writes one tree: a second
asking after the base moved on finds its own branch rather than refusing it.

**No path here is off-limits, tests included.** A fix that arrives with the test
exposing the bug is the fix a person can trust, and that test belongs wherever
the service's tests live - so a tier second-guessing which files a patch may
touch would be refusing the most valuable half of it. What keeps a bad change
out is not this module's opinion of a path: it is that everything lands on a
branch nobody runs, and that merging is a person's act (§13).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import httpx2

from code_host.failures import BranchNotWritten
from code_host.github.headers import write_headers_for
from code_host.github.retries import (
    HttpGet,
    HttpPost,
    Sleep,
    TakenByOtherWork,
    said_of,
    with_retries,
)
from code_host.github.settings import GitHubSettings

logger = logging.getLogger(__name__)

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


def commit_to_new_branch(branch: str,
                         base_commit: str,
                         files: Mapping[str, str],
                         message: str,
                         settings: GitHubSettings,
                         get: HttpGet = httpx2.get,
                         post: HttpPost = httpx2.post,
                         sleep: Sleep = time.sleep) -> str:
    """Commits `files` as one change on `base_commit` and creates `branch`
    pointing at it.

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

    On `base_commit` rather than on a branch's head, because the head moves and
    the commit does not. The caller reads the head once, just before it keeps
    the commit with the fix, and every asking of it - the retries below, or the
    same fix asked again after its answer was lost or its step was run again -
    writes the same tree.

    Each step is asked again where GitHub failed it for a moment, as
    configured. The read and the two objects are asked again as they are - an
    object written twice is one more nothing points at - and the branch is
    looked for before each try of it, the first included: a 500 can come back
    for one GitHub created, and this call can be the second asking of one
    whose answer was lost after the branch was made. Found at the tree this
    call wrote, it is the fix already on its branch, whichever commit holds
    it; found at any other, it is work nobody reviewed as this fix, and the
    branch is refused and left as it is.
    """
    def again[T](step: Callable[[], T], landed: Callable[[], T | None] | None = None) -> T:
        return with_retries(step, retries=settings.github_write_retries,
                            wait_ms=settings.github_write_retry_wait_ms,
                            landed=landed, sleep=sleep)

    base_tree = again(lambda: _tree_of(base_commit, settings, get))

    tree = again(lambda: _write_tree(files, base_tree, settings, post))
    commit = again(lambda: _write_commit(tree, base_commit, message, settings, post))

    try:
        on = again(lambda: _create_branch(branch, commit, settings, post),
                   landed=lambda: _the_branch_holding(branch, tree, settings, get))
    except TakenByOtherWork as taken:
        raise BranchNotWritten(str(taken)) from taken

    logger.info("branch written", extra={"branch": branch, "commit": on})

    return branch


def _tree_of(commit: str,
             settings: GitHubSettings,
             get: HttpGet) -> str:
    """The tree `commit` points at: the base's, which the fix is written over,
    or that of a branch found already there, which says whose work it holds.

    Read rather than assumed, because a new tree must be written over a *tree*
    and what the caller hands over - like what a ref points at - is a *commit*.
    Written over nothing instead, the fix would propose a repository containing
    only the files it touched - every other file in the service deleted, in a
    patch that reads as a small one.
    """
    url = f"{_repository(settings)}/git/commits/{commit}"

    try:
        response = get(url, headers=write_headers_for(settings), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        tree = answered[TREE_FIELD][SHA_FIELD]
    except Exception as error:
        raise BranchNotWritten(
            f"could not read the tree of commit [{commit}] at [{url}]: {said_of(error)}"
        ) from error

    return str(tree)


def _write_tree(files: Mapping[str, str],
                base_tree: str,
                settings: GitHubSettings,
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
                  settings: GitHubSettings,
                  post: HttpPost) -> str:
    """The one commit the fix arrives as.

    Its parent is the base commit, which is what makes it a change *to* that
    code rather than an unrelated history: a commit written without one is a
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
             settings: GitHubSettings,
             post: HttpPost) -> str:
    """Writes one git object and returns the sha the repository gave it.

    A tree and a commit are written the same way and read back the same way, and
    both are useless without the sha - there is nothing to point the next call
    at - so the failure and the extraction are said once rather than twice.
    """
    try:
        response = post(
            url,
            headers=write_headers_for(settings),
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        written = answered[SHA_FIELD]
    except Exception as error:
        raise BranchNotWritten(f"{refused}: {said_of(error)}") from error

    return str(written)


def _create_branch(branch: str,
                   at: str,
                   settings: GitHubSettings,
                   post: HttpPost) -> str:
    """Points a new branch at the finished commit - the last thing written -
    and returns the commit it points at.

    Until this call nothing in the repository refers to the fix at all. That
    ordering is the module's safety: `main` is never a ref this writes, and a
    branch either names a whole commit or was never created.
    """
    url = f"{_repository(settings)}/git/refs"

    try:
        response = post(
            url,
            headers=write_headers_for(settings),
            json={REF_FIELD: f"refs/heads/{branch}", SHA_FIELD: at},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise BranchNotWritten(
            f"could not create branch [{branch}] at [{at}]: {said_of(error)}"
        ) from error

    return at


def _the_branch_holding(branch: str,
                        tree: str,
                        settings: GitHubSettings,
                        get: HttpGet) -> str | None:
    """The commit `branch` points at, where that commit's tree is `tree` - the
    fix this call wrote, on its branch already - or `None` where the look for
    the branch is answered with anything but a 200: no branch, or a look that
    found nothing it can read.

    By the tree rather than the commit: an earlier asking of the same call
    wrote the same tree over the same base, but GitHub dates a commit as it
    writes it, so that asking's commit is another sha for the same fix.

    Raises `TakenByOtherWork` where the branch holds any other tree - a
    different fix, or the name was somebody else's first - naming the branch,
    which a person has to look at.
    """
    url = f"{_repository(settings)}/git/ref/heads/{branch}"
    response = get(url, headers=write_headers_for(settings), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code != httpx2.codes.OK:
        return None

    found: dict[str, Any] = response.json()
    at = str(found[OBJECT_FIELD][SHA_FIELD])
    holding = _tree_of(at, settings, get)

    if holding != tree:
        raise TakenByOtherWork(
            f"could not create branch [{branch}]: the branch already exists, at a "
            f"commit whose tree is not the one this call wrote - [{at}], holding "
            f"[{holding}] where this call wrote [{tree}]"
        )

    return at


def _repository(settings: GitHubSettings) -> str:
    return f"{settings.github_api_url}/repos/{settings.github_repository}"
