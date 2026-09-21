"""The double itself: an HTTP server that speaks GitHub's REST API.

Two surfaces, the same arrangement `anthropic_double` and `slack_double` have:

- `/repos/{owner}/{repo}/...` - what the read and write tiers talk to. Ten
  endpoints, which is exactly the ten Argus uses: three to read source, one to
  say what changed between two commits, five to build a commit and put a branch
  on it, one to propose it.
- `/double-control/*` - what the *test* talks to, to put the repository back and
  to read what was proposed.

Selecting the double is one setting per tier (`GITHUB_API_URL`), which is the
point: nothing in `read_mcp_server`, `write_mcp_server` or `agent_codefix` knows
this file exists.

The owner and repository in the path are accepted and ignored. A double that
checked them would be asserting the caller's configuration, which is the one
thing about this exchange that is already obvious when it is wrong.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Final

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from github_double.repository import (
    BranchAlreadyExists,
    NoSuchObject,
    repository,
)

# Where the double listens. Not an `argus_core` setting, for the reason the
# other doubles' ports are not: the double is not part of Argus, and Argus's own
# config should not grow a field describing a test fixture.
DEFAULT_PORT: Final = int(os.environ.get("GITHUB_DOUBLE_PORT", "8096"))
DEFAULT_BASE_URL: Final = f"http://localhost:{DEFAULT_PORT}"

# GitHub's own vocabulary, named here because this is the module that writes it.
_SHA_FIELD: Final = "sha"
_REF_FIELD: Final = "ref"
_OBJECT_FIELD: Final = "object"
_TREE_FIELD: Final = "tree"
_BASE_TREE_FIELD: Final = "base_tree"
_PARENTS_FIELD: Final = "parents"
_PATH_FIELD: Final = "path"
_TYPE_FIELD: Final = "type"
_MODE_FIELD: Final = "mode"
_CONTENT_FIELD: Final = "content"
_ENCODING_FIELD: Final = "encoding"
_TRUNCATED_FIELD: Final = "truncated"
_MESSAGE_FIELD: Final = "message"
_TITLE_FIELD: Final = "title"
_BODY_FIELD: Final = "body"
_HEAD_FIELD: Final = "head"
_BASE_FIELD: Final = "base"
_DRAFT_FIELD: Final = "draft"
_NUMBER_FIELD: Final = "number"
_READABLE_AT_FIELD: Final = "html_url"
_FILES_FIELD: Final = "files"
_FILENAME_FIELD: Final = "filename"

# How a comparison names its two ends in the path: base first, three dots, head.
_BETWEEN: Final = "..."

_HEADS_PREFIX: Final = "heads/"

_FILE_ENTRY_TYPE: Final = "blob"
_FILE_MODE: Final = "100644"
_BASE64_ENCODING: Final = "base64"

_REFS_PREFIX: Final = "refs/heads/"

_NOT_FOUND_STATUS: Final = 404
_UNPROCESSABLE_STATUS: Final = 422
_CREATED_STATUS: Final = 201

app = FastAPI(title="github double")


@app.get("/repos/{owner}/{repo}/git/trees/{ref}")
def list_the_tree(owner: str, repo: str, ref: str) -> JSONResponse:
    """Every path at a ref, which is how the read tier lists the source.

    Never truncated. The real API truncates a large tree and says so, and the
    read tier refuses that answer rather than reporting a partial repository -
    a behaviour worth having and not worth faking, since a fixture repository
    cannot reach the size that triggers it.
    """
    try:
        held = repository.files_at(ref)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({
        _SHA_FIELD: ref,
        _TRUNCATED_FIELD: False,
        _TREE_FIELD: [
            {
                _PATH_FIELD: path,
                _TYPE_FIELD: _FILE_ENTRY_TYPE,
                _MODE_FIELD: _FILE_MODE
            }
            for path in sorted(held)
        ]
    })


@app.get("/repos/{owner}/{repo}/contents/{path:path}")
def read_one_file(owner: str, repo: str, path: str, ref: str = "main") -> JSONResponse:
    """One file's content, base64 as the API sends it.

    Answers a blob sha too. Nothing reads it any more - the write tier stopped
    needing it when a fix became one commit - but the field is part of what this
    endpoint is, and a double that dropped it would let a caller start depending
    on its absence.
    """
    try:
        held = repository.files_at(ref)
    except NoSuchObject as absent:
        return _not_found(absent)

    if path not in held:
        return _not_found(NoSuchObject(f"no file [{path}] at [{ref}]"))

    return JSONResponse({
        _PATH_FIELD: path,
        _SHA_FIELD: repository.write_tree({path: held[path]}),
        _ENCODING_FIELD: _BASE64_ENCODING,
        _CONTENT_FIELD: base64.b64encode(held[path].encode()).decode()
    })


@app.get("/repos/{owner}/{repo}/tarball/{ref}")
def download_the_archive(owner: str, repo: str, ref: str) -> Response:
    """The whole repository as a tar.gz, which is how the read tier searches it.

    Served directly rather than through the redirect the real API answers with.
    The read tier already follows redirects, so the hop is real behaviour this
    could imitate - but imitating it would only test httpx, and a double that
    redirected to a second host of its own would be two fixtures.
    """
    try:
        archive = repository.archive_of(ref)
    except NoSuchObject as absent:
        return _not_found(absent)

    return Response(content=archive, media_type="application/gzip")


@app.get("/repos/{owner}/{repo}/commits/{ref:path}")
def read_the_commit_a_ref_points_at(owner: str, repo: str, ref: str) -> JSONResponse:
    """Where a ref points, as the catch-up pass asks it.

    The commits API rather than the git-data one two endpoints below, and they
    are not interchangeable: that one takes a commit id and answers its tree,
    this one takes anything nameable - `heads/main`, a tag, a sha - and answers
    which commit it is. A catch-up pass with no push on record asks this, so a
    double without it leaves the index unbuildable for exactly the deployment
    that has no webhook.

    `heads/` is stripped because that is how a branch is named to an endpoint
    that also takes tags: the caller says `heads/main` precisely so a `main`
    tag cannot answer for the `main` branch. This double holds no tags, so the
    prefix is the caller's precision and nothing here has to act on it.
    """
    named = ref.removeprefix(_HEADS_PREFIX)

    try:
        commit = (
            repository.head_of(named)
            if named in repository.branches()
            else repository.tree_of(named) and named
        )
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({_SHA_FIELD: commit})


@app.get("/repos/{owner}/{repo}/compare/{basehead:path}")
def compare_two_commits(owner: str, repo: str, basehead: str) -> JSONResponse:
    """What changed between two commits - the index's question, not a fix's.

    The one endpoint here that exists for `code_index` rather than for Code-Fix.
    A catch-up pass with an index already asks what moved since the commit it was
    built from and reconsiders only that, so without this the incremental half
    of spec §11 can never run against a stack - every pass would either backfill
    or fail, and a suite that pushed would be asserting a gap nothing closes.

    `base...head` in one segment, as GitHub spells it, matched as a path so a
    branch name carrying a slash survives. Split on the first separator only:
    neither half of a malformed pair is worth guessing at, and a sha has no
    dots to be confused by.

    Never truncated, and that is worth saying because the caller defends against
    it: the real comparison lists at most three hundred files and says nothing
    about having stopped. The fixture is three, so this double cannot exercise
    that ceiling and must not pretend to - a `files` list here is complete.

    A rename arrives as both of its paths, since it is a file that went and a
    file that arrived, which is the same pair the real API reports under
    `previous_filename`.
    """
    base, separator, head = basehead.partition(_BETWEEN)

    if not separator:
        return _not_found(
            NoSuchObject(f"no comparison [{basehead}]: expected base{_BETWEEN}head")
        )

    try:
        changed = repository.changed_between(base, head)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse(
        {_FILES_FIELD: [{_FILENAME_FIELD: path} for path in changed]}
    )


@app.get("/repos/{owner}/{repo}/git/ref/heads/{branch:path}")
def read_the_ref(owner: str, repo: str, branch: str) -> JSONResponse:
    """The commit a branch points at - the write tier's first question."""
    try:
        head = repository.head_of(branch)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({
        _REF_FIELD: f"{_REFS_PREFIX}{branch}",
        _OBJECT_FIELD: {_SHA_FIELD: head}
    })


@app.get("/repos/{owner}/{repo}/git/commits/{commit}")
def read_the_commit(owner: str, repo: str, commit: str) -> JSONResponse:
    """The tree a commit points at - the write tier's second question."""
    try:
        tree = repository.tree_of(commit)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({
        _SHA_FIELD: commit,
        _TREE_FIELD: {_SHA_FIELD: tree}
    })


@app.post("/repos/{owner}/{repo}/git/trees")
async def write_the_tree(owner: str, repo: str, request: Request) -> JSONResponse:
    """A tree written over the base's, from entries carrying their content.

    Content inline rather than blob shas, because that is the form Argus sends:
    the API writes the blob itself and uses its sha, which is what makes the
    number of requests a property of the fix being one change.
    """
    asked: dict[str, Any] = await request.json()
    entries = asked.get(_TREE_FIELD) or []
    written = {
        entry[_PATH_FIELD]: entry[_CONTENT_FIELD]
        for entry in entries
        if _PATH_FIELD in entry and _CONTENT_FIELD in entry
    }

    try:
        sha = repository.written_over(asked[_BASE_TREE_FIELD], written)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({_SHA_FIELD: sha}, status_code=_CREATED_STATUS)


@app.post("/repos/{owner}/{repo}/git/commits")
async def write_the_commit(owner: str, repo: str, request: Request) -> JSONResponse:
    """One commit, on the parents it named."""
    asked: dict[str, Any] = await request.json()

    try:
        sha = repository.write_commit(
            asked[_TREE_FIELD], list(asked.get(_PARENTS_FIELD) or [])
        )
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse({_SHA_FIELD: sha}, status_code=_CREATED_STATUS)


@app.post("/repos/{owner}/{repo}/git/refs")
async def create_the_ref(owner: str, repo: str, request: Request) -> JSONResponse:
    """The branch, pointed at the finished commit - the last thing written.

    A branch that already exists is refused with the status the real API uses.
    That refusal is not an edge case here: it is what a second run of the same
    incident meets, and the write tier is written to stop rather than propose.
    """
    asked: dict[str, Any] = await request.json()
    branch = str(asked.get(_REF_FIELD, "")).removeprefix(_REFS_PREFIX)

    try:
        repository.create_ref(branch, asked[_SHA_FIELD])
    except BranchAlreadyExists as taken:
        return _refused(taken)
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse(
        {
            _REF_FIELD: f"{_REFS_PREFIX}{branch}",
            _OBJECT_FIELD: {_SHA_FIELD: asked[_SHA_FIELD]}
        },
        status_code=_CREATED_STATUS
    )


@app.post("/repos/{owner}/{repo}/pulls")
async def open_the_pull_request(owner: str, repo: str, request: Request) -> JSONResponse:
    """The proposal itself, numbered as a repository numbers one.

    The draft flag is answered back rather than assumed. What Argus may and may
    not do to a repository is the subject of spec §13, and a double that
    reported every proposal as a draft would agree with a write tier that had
    stopped sending one.
    """
    asked: dict[str, Any] = await request.json()

    try:
        proposal = repository.propose(
            title=str(asked.get(_TITLE_FIELD, "")),
            body=str(asked.get(_BODY_FIELD, "")),
            head=str(asked.get(_HEAD_FIELD, "")),
            base=str(asked.get(_BASE_FIELD, "")),
            draft=bool(asked.get(_DRAFT_FIELD, False))
        )
    except NoSuchObject as absent:
        return _not_found(absent)

    return JSONResponse(
        {
            _NUMBER_FIELD: proposal.number,
            _READABLE_AT_FIELD: proposal.html_url,
            _TITLE_FIELD: proposal.title,
            _BODY_FIELD: proposal.body,
            _DRAFT_FIELD: proposal.draft,
            _HEAD_FIELD: {_REF_FIELD: proposal.head},
            _BASE_FIELD: {_REF_FIELD: proposal.base}
        },
        status_code=_CREATED_STATUS
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness probe, so a test harness can wait for the port to answer."""
    return {"status": "ok"}


@app.post("/double-control/reset")
def put_the_repository_back() -> dict[str, str]:
    """One branch holding the fixture, and nothing proposed.

    What a suite calls between cases. Without it the second case in a file finds
    the first case's branch already there, and the failure - a refused branch
    reported as "could not propose a fix" - looks like the code's.
    """
    repository.reset()

    return {"status": "reset"}


@app.get("/double-control/pulls")
def what_was_proposed() -> dict[str, Any]:
    """Every proposal opened since the last reset, in order.

    Whole rather than counted, for the reason the Slack double keeps messages:
    a test asking "did Code-Fix propose the right thing" needs the title and the
    branch, and a tally answers a question nobody has.
    """
    return {"pulls": [proposal.model_dump() for proposal in repository.proposals]}


@app.get("/double-control/branches")
def what_was_written() -> dict[str, Any]:
    """Every branch and the files on it.

    The other half of what a proposal means: a pull request is a promise about a
    branch, and a suite that read only the proposals could not tell a fix that
    wrote the patch from one that opened an empty change.
    """
    return {
        "branches": {
            branch: sorted(repository.files_at(branch))
            for branch in repository.branches()
        }
    }


def _not_found(absent: Exception) -> JSONResponse:
    return JSONResponse(
        {_MESSAGE_FIELD: str(absent)}, status_code=_NOT_FOUND_STATUS
    )


def _refused(taken: Exception) -> JSONResponse:
    return JSONResponse(
        {_MESSAGE_FIELD: str(taken)}, status_code=_UNPROCESSABLE_STATUS
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=DEFAULT_PORT)
