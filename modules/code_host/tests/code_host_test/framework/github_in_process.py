"""GitHub as the ports' suite reaches it: `github_double`, served in-process.

Not a second stand-in for GitHub. `github_double` is the one every stack runs,
so it is the one kept right (`tests/contract/github` holds its comparisons to
GitHub's), and a stand-in of this suite's own would be a second thing to keep
right. Its app is asked here through Starlette's `TestClient`, and each answer
handed to the adapter as the `httpx2.Response` it reads - with the request it
answered, without which `raise_for_status` cannot run.

A seed is staged through the double's own surfaces alone: its control seam for
commits, and GitHub's own route for branches. The double holds one repository
for the whole process, so the suite puts it back after every case.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import httpx2
from code_host_double import RepositoryState
from fastapi.testclient import TestClient
from github_double.server import app

# Where the adapter is told GitHub's API answers: the address `TestClient`
# serves the app at, which reaches nothing outside this process.
THE_DOUBLES_ADDRESS: Final = "http://testserver"

# The double's wire, as this suite's seeding speaks it.
_REFS_PREFIX: Final = "refs/heads/"

# The media type an answer is handed on under where the double named none.
_SOME_BYTES: Final = "application/octet-stream"


class GitHubInProcess:
    """The double's app, asked in this process.

    `unreachable` builds one nothing reaches: every request the adapter makes
    fails as one that never arrived. Seeding and reading back are this suite's
    own, and reach it whatever `unreachable` says.
    """

    def __init__(self, *, unreachable: bool = False) -> None:
        self._client = TestClient(app, base_url=THE_DOUBLES_ADDRESS)
        self._unreachable = unreachable

    def holding(self, state: RepositoryState, repository: str) -> GitHubInProcess:
        """The double put back, then holding `state`: each commit staged with
        its files and parents, then each branch created as GitHub creates one."""
        self.put_back()

        for commit in state.commits:
            self._client.post("/double-control/stage-commit", json={
                "sha": commit.sha,
                "files": dict(commit.files),
                "parents": list(commit.parents)
            }).raise_for_status()

        for branch, sha in state.branches:
            self._client.post(f"/repos/{repository}/git/refs", json={
                "ref": f"{_REFS_PREFIX}{branch}",
                "sha": sha
            }).raise_for_status()

        return self

    def get(self,
            url: str,
            *,
            headers: Mapping[str, str] | None = None,
            params: Mapping[str, str] | None = None,
            **dont_care_options: Any) -> httpx2.Response:
        """A GET as the adapter makes one - its timeout and redirects passed
        over, since nothing here waits or moves."""
        request = httpx2.Request("GET", url, params=params)
        self._reached(request)

        return _as_read(self._client.get(url, headers=headers, params=params), request)

    def post(self,
             url: str,
             *,
             headers: Mapping[str, str] | None = None,
             json: Any = None,
             **dont_care_options: Any) -> httpx2.Response:
        """A POST as the adapter makes one - its timeout passed over."""
        request = httpx2.Request("POST", url)
        self._reached(request)

        return _as_read(self._client.post(url, headers=headers, json=json), request)

    def proposed(self) -> list[tuple[str, str, str, str, bool]]:
        """Every pull request opened since the double was put back: its head,
        base, title, body and whether it is a draft."""
        answered = self._client.get("/double-control/pulls")
        answered.raise_for_status()

        return [(pull["head"], pull["base"], pull["title"], pull["body"], pull["draft"])
                for pull in answered.json()["pulls"]]

    def put_back(self) -> None:
        """The double as it starts: one branch holding the shop's fixture, and
        nothing proposed."""
        self._client.post("/double-control/reset").raise_for_status()

    def _reached(self, request: httpx2.Request) -> None:
        if self._unreachable:
            raise httpx2.ConnectError("the double is not reachable", request=request)


def _as_read(answered: Any, request: httpx2.Request) -> httpx2.Response:
    """The app's answer as the adapter's HTTP library hands one over."""
    return httpx2.Response(
        answered.status_code,
        content=answered.content,
        headers={"content-type": answered.headers.get("content-type", _SOME_BYTES)},
        request=request
    )
