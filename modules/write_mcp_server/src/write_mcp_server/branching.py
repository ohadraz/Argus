"""Putting a proposed fix on a branch of its own (spec §7.4, §13, §15.1).

The half of Code-Fix's outward act that touches code, and it touches only a
branch. Nothing here can write to `main`: the branch is created first and every
write names it explicitly, so the worst a wrong patch can do is exist somewhere
nobody is running. What makes that change is a human merging it, which is not
something this server can do (see `pull_requests`).

Separate from opening the pull request because the two fail differently and a
caller needs to tell them apart - a push that was rejected and a proposal that
was never made are different situations, and a module doing both would report
them through one exception.

**A fix may not rewrite the test that grades it.** The ground-truth fixture is
what says whether a patch worked (§15.1), so a patch able to edit it could turn
a scenario green by deleting the question, and every benchmark figure after that
would be measuring nothing. The refusal lives here, on the tier that can
actually write, rather than in a prompt the agent could reason its way past.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from typing import Any, Final

import httpx

from write_mcp_server.pull_requests import RepositoryWriteSettings

HttpGet = Callable[..., httpx.Response]
HttpPost = Callable[..., httpx.Response]
HttpPut = Callable[..., httpx.Response]

REQUEST_TIMEOUT_SECONDS = 10.0

# The one path in the Target Service's repository that Code-Fix may not write
# to (spec §13, §15.1). A constant rather than a setting: it is a fact about how
# the benchmark is built, not a knob a deployment turns, and a deployment able
# to turn it off is a deployment able to stop grading honestly.
THE_GROUND_TRUTH_FIXTURE: Final = "tests/io_shop/test_spend_summary.py"

# GitHub's wire vocabulary, named for the fields that carry it. `SHA_FIELD` is
# two different things under one spelling and that is the API's doing, not
# ours: on a ref it is the commit a branch points at, on a write it is the blob
# being replaced - which is why the two are read through different names below.
REF_FIELD: Final = "ref"
OBJECT_FIELD: Final = "object"
SHA_FIELD: Final = "sha"
MESSAGE_FIELD: Final = "message"
CONTENT_FIELD: Final = "content"
BRANCH_FIELD: Final = "branch"

ACCEPT_HEADER: Final = "application/vnd.github+json"


class BranchNotWritten(Exception):
    """The fix is not on a branch, whatever the reason.

    One exception for an unreachable host, a rejected credential, a branch that
    already existed, a write the repository refused and a patch that reached for
    its own grader - because the caller's next move is the same for all five:
    there is nothing to open a pull request from, so it must not open one.

    It says nothing about what was left behind. A push cannot be un-pushed from
    here, so a failure partway through leaves a branch with some of the patch on
    it; what matters is that nobody proposes it as though it were whole.
    """


def commit_to_new_branch(branch: str,
                         base_branch: str,
                         files: Mapping[str, str],
                         message: str,
                         settings: RepositoryWriteSettings,
                         get: HttpGet = httpx.get,
                         post: HttpPost = httpx.post,
                         put: HttpPut = httpx.put) -> str:
    """Creates `branch` off `base_branch` and writes `files` onto it.

    `files` maps a repository path to that file's **whole** new content, not to
    a diff. A patch is applied by the model that wrote it, not here: applying a
    diff is a second thing that can fail, and it fails by producing a file that
    is subtly not what anyone intended rather than by raising.

    Returns the branch it wrote, so the caller can hand it straight to
    `open_pull_request` without re-deriving a name that has to match.

    Raises `BranchNotWritten` if any path is the ground-truth fixture - before
    anything at all is written - or if the repository refuses any step.
    """
    _refuse_to_touch_the_grader(files)

    base_head = _head_of(base_branch, settings, get)
    _create_branch(branch, base_head, settings, post)

    for path, content in files.items():
        _write(path, content, branch, base_branch, message, settings, get, put)

    return branch


def _refuse_to_touch_the_grader(files: Mapping[str, str]) -> None:
    """Refused whole, and refused first.

    Checking every path before writing any of them is the point: writing the
    innocent files and failing on the last would leave a half-applied patch on a
    branch, which is a proposal for a change nobody made and which reads, to
    anyone who opens it, exactly like a change somebody did.
    """
    reached_for = [path for path in files if path == THE_GROUND_TRUTH_FIXTURE]

    if reached_for:
        raise BranchNotWritten(
            f"a fix may not rewrite the test that grades it: {reached_for}"
        )


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


def _create_branch(branch: str,
                   at: str,
                   settings: RepositoryWriteSettings,
                   post: HttpPost) -> None:
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


def _write(path: str,
           content: str,
           branch: str,
           base_branch: str,
           message: str,
           settings: RepositoryWriteSettings,
           get: HttpGet,
           put: HttpPut) -> None:
    """Writes one file onto the branch, replacing whatever was there.

    `branch` is named on every write. The Contents API writes to the
    repository's default branch when no branch is given, so a write that forgot
    to say would land on `main` - the one outcome this module exists to make
    impossible, and one that would be silent.
    """
    url = f"{_repository(settings)}/contents/{path}"
    body: dict[str, Any] = {
        MESSAGE_FIELD: message,
        CONTENT_FIELD: base64.b64encode(content.encode()).decode(),
        BRANCH_FIELD: branch
    }

    replacing = _blob_at(path, base_branch, settings, get)

    if replacing is not None:
        body[SHA_FIELD] = replacing

    try:
        response = put(
            url,
            headers=_headers(settings),
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise BranchNotWritten(
            f"could not write [{path}] onto [{branch}]: {error}"
        ) from error


def _blob_at(path: str,
             base_branch: str,
             settings: RepositoryWriteSettings,
             get: HttpGet) -> str | None:
    """The blob this write replaces, or `None` for a file the fix adds.

    The API refuses an update that does not name the version it replaces, and
    refuses a *creation* that names one - so the two cases are genuinely
    different calls and the absence has to be real rather than an empty string.

    Anything other than a readable answer is treated as "no previous version",
    including a 404, which is the ordinary way the API says a fix brought a new
    file. A wrong guess here does not pass silently: the write that follows is
    the one the repository rejects.
    """
    url = f"{_repository(settings)}/contents/{path}"

    try:
        response = get(
            url,
            headers=_headers(settings),
            params={REF_FIELD: base_branch},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code != httpx.codes.OK:
            return None

        answered: dict[str, Any] = response.json()
    except Exception:
        return None

    blob = answered.get(SHA_FIELD)

    return blob if isinstance(blob, str) else None


def _repository(settings: RepositoryWriteSettings) -> str:
    return f"{settings.github_api_url}/repos/{settings.github_repository}"


def _headers(settings: RepositoryWriteSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": ACCEPT_HEADER
    }
