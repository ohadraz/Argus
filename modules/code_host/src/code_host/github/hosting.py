"""The code host's ports, as GitHub answers them.

Two classes, one per port, because the two credentials are not
interchangeable. `GitHubReads` holds the read token alone and is the read
tier's and the index's - its settings have no field to put the other in, which
is what keeps `argus-read-mcp` incapable of mutation rather than merely
disinclined (spec §13). `GitHub` holds the token that pushes and is the write
tier's, and offers no read: the only reads made under that token are the ones a
write makes to know where it stands.

Each method is one sentence of wiring. What a request looks like, how its answer
is read and how it fails is the module beside this one that the method names,
and is asserted there; what is asserted here is that each method reaches it,
under the credential its class holds.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import httpx2
from core.models import OpenedPullRequest, RevisionSource

from code_host.github import (
    branching,
    comparing,
    containing,
    differences,
    heads,
    listing,
    pages,
    pull_requests,
    reading,
)
from code_host.github.retries import HttpGet, HttpPost, Sleep
from code_host.github.settings import GitHubReadSettings, GitHubSettings
from code_host.port import SourceDifference


class GitHubReads:
    """The reads port, answered by one GitHub repository under one credential.

    `get` is where a test puts GitHub; left out, requests go over the network.
    """

    def __init__(self, settings: GitHubReadSettings, get: HttpGet = httpx2.get) -> None:
        self._settings = settings
        self._get = get

    @property
    def repository(self) -> str:
        """The repository, as `owner/name`."""
        return self._settings.github_repository

    def files_at(self, ref: str, /) -> list[str]:
        """Every file at `ref` (`listing.list_repository_files`)."""
        return listing.list_repository_files(ref, self._settings, self._get)

    def file_at(self, path: str, ref: str, /) -> str:
        """What one file says at `ref` (`listing.read_repository_file`)."""
        return listing.read_repository_file(path, ref, self._settings, self._get)

    def source_at(self, ref: str, /) -> dict[str, str]:
        """Every readable file at `ref` (`reading.the_source_at`)."""
        return reading.the_source_at(ref, self._settings, self._get)

    def difference_between(self, base: str, head: str, /) -> SourceDifference:
        """What differs between two commits (`differences.the_difference_between`)."""
        return differences.the_difference_between(base, head, self._settings, self._get)

    def paths_changed_between(self, base: str, head: str, /) -> list[str] | None:
        """Which paths differ between two commits (`comparing.paths_changed_between`)."""
        return comparing.paths_changed_between(base, head, self._settings, self._get)

    def head_of(self, branch: str, /) -> str:
        """Where `branch` points (`heads.the_head_of`)."""
        return heads.the_head_of(branch, self._settings, self._get)

    def contains(self, branch: str, revision: str, /) -> bool:
        """Whether `revision` is in `branch`'s history
        (`containing.the_branch_contains`)."""
        return containing.the_branch_contains(branch, revision, self._settings, self._get)

    def where_to_read(self,
                      repo_url: str,
                      revision: str,
                      path: str | None,
                      /) -> RevisionSource | None:
        """A deployed revision's pages, on github.com (`pages.where_to_read`)."""
        return pages.where_to_read(repo_url, revision, path)


class GitHub:
    """The writes port, answered by one GitHub repository under the token that
    pushes - and nothing else: it offers no read, so none is ever made under
    that token but what a write itself has to know.

    `get`, `post` and `sleep` are where a test puts GitHub and the wait between
    tries; left out, requests go over the network and the waits are real.
    """

    def __init__(self,
                 settings: GitHubSettings,
                 get: HttpGet = httpx2.get,
                 post: HttpPost = httpx2.post,
                 sleep: Sleep = time.sleep) -> None:
        self._settings = settings
        self._get = get
        self._post = post
        self._sleep = sleep

    def commit_to_new_branch(self,
                             branch: str,
                             base_commit: str,
                             files: Mapping[str, str],
                             message: str,
                             /) -> str:
        """The fix as one commit on `base_commit`, on a branch of its own
        (`branching.commit_to_new_branch`)."""
        return branching.commit_to_new_branch(branch, base_commit, files, message,
                                              self._settings,
                                              self._get, self._post, self._sleep)

    def propose(self, head: str, base: str, title: str, body: str, /) -> OpenedPullRequest:
        """A draft pull request from `head` onto `base`
        (`pull_requests.open_pull_request`)."""
        return pull_requests.open_pull_request(head, base, title, body,
                                               self._settings,
                                               self._post, self._get, self._sleep)
