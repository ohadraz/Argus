"""The code host's ports, as GitHub answers them.

Each method is wiring - what a request looks like and how its answer is read is
asserted in the module it names. What is asserted here is what the wiring alone
can get wrong: which credential each class asks under, and, wherever two
arguments are both strings, which is which. A base and a head passed the wrong
way round still type-check, and invert every deployment diff a model reads.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_testkit.assertions import Assertion, all_of, the_answer_was
from argus_testkit.scenario import Scenario
from code_host import SourceDifference
from code_host.github import GitHub, GitHubReads
from code_host.github.branching import OBJECT_FIELD, REF_FIELD, SHA_FIELD, TREE_FIELD
from code_host.github.comparing import AHEAD, BETWEEN, FILES_FIELD, RELATION_FIELD
from code_host.github.headers import AUTHORIZATION_HEADER, BEARER_SCHEME
from code_host.github.listing import CONTENT_FIELD
from code_host.github.listing import REF_FIELD as THE_REF_PARAMETER
from code_host.github.pull_requests import (
    BASE_FIELD,
    BODY_FIELD,
    HEAD_FIELD,
    NUMBER_FIELD,
    READABLE_AT_FIELD,
    TITLE_FIELD,
)
from core.models import OpenedPullRequest, RevisionSource

from code_host_test.framework.settings import some_repository_settings, some_settings

SOME_REPOSITORY = "kuki/io-shop"
SOME_READ_TOKEN = "ghp_some-read-only-token"
SOME_TOKEN = "ghp_some-token-that-pushes"
DONT_CARE_BRANCH = "main"
SOME_HEAD = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

# A read of one file: where it is, and the commit it is read at.
SOME_PATH = "src/io_shop/spend_summary.py"
SOME_REF = "9abaec7"
SOME_SOURCE = "def average(account): ...\n"

# Two commits compared, in the order a deployment is read: the one before, then
# the one deployed.
THE_REVISION_BEFORE = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
THE_REVISION_DEPLOYED = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"

# Whether a branch holds a revision: the branch read, and the revision that ran.
SOME_BRANCH = "release"
SOME_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"

# Where a deployed revision is read: the repository a platform synced from, and
# the directory in it.
SOME_CLONE_ADDRESS = "https://github.com/kuki/k8s-configs.git"
THE_REPOSITORY_IT_NAMES = "kuki/k8s-configs"
SOME_DIRECTORY = "deploy"

# A fix as it is proposed: the branch it is put on, the one it is cut from, and
# its words.
SOME_FIX_BRANCH = "argus/fix-monthly-spend"
SOME_BASE_BRANCH = "main"
DONT_CARE_FILES = {"src/io_shop/spend_summary.py": "def average(account): ...\n"}
DONT_CARE_MESSAGE = "dont care message"
SOME_TITLE = "Average spend over the items bought this month"
SOME_BODY = "The month's items, not the account's."
# The objects a commit is built from, as GitHub names them.
THE_BASE_HEAD = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
THE_BASE_TREE = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_FIX_TREE = "a97029318f2d4c6b8e0a1c3e5f7092b4d6f8a0c2"
THE_FIX_COMMIT = "3f1b9d2c8a7e6f5d4c3b2a1908f7e6d5c4b3a291"

SOME_PULL_REQUEST_NUMBER = 7
SOME_PULL_REQUEST_PAGE = "https://github.com/kuki/io-shop/pull/7"


@pytest.mark.unit
def test_the_repository_is_the_one_configured() -> None:
    Scenario() \
        .when(lambda: GitHubReads(some_settings(repository=SOME_REPOSITORY)).repository) \
        .then(the_answer_was(SOME_REPOSITORY))


@pytest.mark.unit
def test_the_read_tier_s_adapter_reads_under_the_read_token() -> None:
    # The read tier's whole claim: what it holds cannot push.
    get = a_github_answering({SHA_FIELD: SOME_HEAD})

    Scenario() \
        .when(lambda: GitHubReads(some_settings(read_token=SOME_READ_TOKEN), get)
              .head_of(DONT_CARE_BRANCH)) \
        .then(all_of(
            the_answer_was(SOME_HEAD),
            _every_request_was_authorized_with(get, f"{BEARER_SCHEME} {SOME_READ_TOKEN}")
        ))


@pytest.mark.unit
def test_a_file_is_read_at_the_path_and_ref_asked_for() -> None:
    get = a_github_answering({CONTENT_FIELD: base64.b64encode(SOME_SOURCE.encode()).decode()})

    Scenario() \
        .when(lambda: GitHubReads(some_settings(), get).file_at(SOME_PATH, SOME_REF)) \
        .then(all_of(
            the_answer_was(SOME_SOURCE),
            _a_request_ended_with(get, f"/contents/{SOME_PATH}"),
            _the_request_named_the_ref(get, SOME_REF)
        ))


@pytest.mark.unit
def test_a_difference_is_taken_from_the_base_to_the_head() -> None:
    # Reversed, a deployment reads as its own undoing: a port it moved reads as
    # one it put back.
    get = a_github_answering({RELATION_FIELD: AHEAD, FILES_FIELD: []})

    Scenario() \
        .when(lambda: GitHubReads(some_settings(), get)
              .difference_between(THE_REVISION_BEFORE, THE_REVISION_DEPLOYED)) \
        .then(all_of(
            _a_difference_between(THE_REVISION_BEFORE, THE_REVISION_DEPLOYED),
            _a_request_ended_with(
                get, f"/compare/{THE_REVISION_BEFORE}{BETWEEN}{THE_REVISION_DEPLOYED}"
            )
        ))


@pytest.mark.unit
def test_the_paths_changed_are_compared_from_the_base_to_the_head() -> None:
    get = a_github_answering({RELATION_FIELD: AHEAD, FILES_FIELD: []})

    Scenario() \
        .when(lambda: GitHubReads(some_settings(), get)
              .paths_changed_between(THE_REVISION_BEFORE, THE_REVISION_DEPLOYED)) \
        .then(_a_request_ended_with(
            get, f"/compare/{THE_REVISION_BEFORE}{BETWEEN}{THE_REVISION_DEPLOYED}"
        ))


@pytest.mark.unit
def test_whether_a_branch_holds_a_revision_compares_the_revision_to_the_branch() -> None:
    # Reversed, `ahead` would say the revision had moved past the branch.
    get = a_github_answering({RELATION_FIELD: AHEAD})

    Scenario() \
        .when(lambda: GitHubReads(some_settings(), get).contains(SOME_BRANCH, SOME_REVISION)) \
        .then(all_of(
            the_answer_was(True),
            _a_request_ended_with(get, f"/compare/{SOME_REVISION}{BETWEEN}{SOME_BRANCH}")
        ))


@pytest.mark.unit
def test_a_deployed_revision_is_read_at_its_commit_and_its_directory() -> None:
    Scenario() \
        .when(lambda: GitHubReads(some_settings())
              .where_to_read(SOME_CLONE_ADDRESS, SOME_REVISION, SOME_DIRECTORY)) \
        .then(_pages_of(THE_REPOSITORY_IT_NAMES, SOME_REVISION, SOME_DIRECTORY))


@pytest.mark.unit
def test_the_write_tier_s_adapter_writes_under_the_token_that_pushes() -> None:
    # The one credential its settings hold, for the writes and for what a write
    # reads on the way.
    get, post = a_github_holding_a_base(SOME_BASE_BRANCH)

    Scenario() \
        .when(lambda: GitHub(some_repository_settings(token=SOME_TOKEN), get, post)
              .commit_to_new_branch(SOME_FIX_BRANCH, SOME_BASE_BRANCH, DONT_CARE_FILES,
                                    DONT_CARE_MESSAGE)) \
        .then(all_of(
            _every_request_was_authorized_with(get, f"{BEARER_SCHEME} {SOME_TOKEN}"),
            _every_request_was_authorized_with(post, f"{BEARER_SCHEME} {SOME_TOKEN}")
        ))


@pytest.mark.unit
def test_a_fix_is_committed_to_its_own_branch_cut_from_the_base() -> None:
    # Two branches, both strings. Swapped, the fix is cut from a branch that does
    # not exist and the ref written is the base's - the one thing this write
    # must never touch.
    get, post = a_github_holding_a_base(SOME_BASE_BRANCH)

    Scenario() \
        .when(lambda: GitHub(some_repository_settings(), get, post).commit_to_new_branch(
            SOME_FIX_BRANCH, SOME_BASE_BRANCH, DONT_CARE_FILES, DONT_CARE_MESSAGE
        )) \
        .then(all_of(
            the_answer_was(SOME_FIX_BRANCH),
            _the_ref_written_was(post, f"refs/heads/{SOME_FIX_BRANCH}")
        ))


@pytest.mark.unit
def test_a_fix_is_proposed_from_its_branch_onto_the_base_in_its_own_words() -> None:
    # Four strings: swapped branches propose the base onto the fix, and a
    # swapped title and body put the case for it where its name goes.
    post = a_github_opening_a_pull_request()
    get = a_github_answering([])

    Scenario() \
        .when(lambda: GitHub(some_repository_settings(), get, post).propose(
            SOME_FIX_BRANCH, SOME_BASE_BRANCH, SOME_TITLE, SOME_BODY
        )) \
        .then(all_of(
            the_answer_was(OpenedPullRequest(number=SOME_PULL_REQUEST_NUMBER,
                                             url=SOME_PULL_REQUEST_PAGE,
                                             branch=SOME_FIX_BRANCH)),
            _the_proposal_asked_was(post, head=SOME_FIX_BRANCH, base=SOME_BASE_BRANCH,
                                    title=SOME_TITLE, body=SOME_BODY)
        ))


def _answered(status_code: int, body: Any) -> httpx2.Response:
    return httpx2.Response(status_code=status_code, json=body,
                           request=httpx2.Request("GET", "http://github.invalid/"))


def a_github_answering(body: Any) -> Any:
    """GitHub answering every read with `body`."""
    get = create_autospec(httpx2.get)
    get.return_value = _answered(200, body)

    return get


def a_github_opening_a_pull_request() -> Any:
    post = create_autospec(httpx2.post)
    post.return_value = _answered(201, {NUMBER_FIELD: SOME_PULL_REQUEST_NUMBER,
                                        READABLE_AT_FIELD: SOME_PULL_REQUEST_PAGE})

    return post


def a_github_holding_a_base(base: str) -> tuple[Any, Any]:
    """GitHub as the Git Data API answers a fix cut from `base`: its head and
    tree read, no branch of the fix's name yet, and each object written."""
    def reading(url: str, **dont_care: Any) -> httpx2.Response:
        if url.endswith(f"/git/ref/heads/{base}"):
            return _answered(200, {OBJECT_FIELD: {SHA_FIELD: THE_BASE_HEAD}})

        if url.endswith(f"/git/commits/{THE_BASE_HEAD}"):
            return _answered(200, {TREE_FIELD: {SHA_FIELD: THE_BASE_TREE}})

        return _answered(404, {})

    def writing(url: str, **dont_care: Any) -> httpx2.Response:
        if url.endswith("/git/trees"):
            return _answered(201, {SHA_FIELD: THE_FIX_TREE})

        if url.endswith("/git/commits"):
            return _answered(201, {SHA_FIELD: THE_FIX_COMMIT})

        return _answered(201, {})

    get = create_autospec(httpx2.get, side_effect=reading)
    post = create_autospec(httpx2.post, side_effect=writing)

    return get, post


def _every_request_was_authorized_with(sent_by: Any, credential: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        sent = [made.kwargs["headers"].get(AUTHORIZATION_HEADER)
                for made in sent_by.call_args_list]

        if not sent or any(each != credential for each in sent):
            raise AssertionError(
                f"Expected every request authorized with [{credential}], they bore {sent}"
            )

        return True

    return assertion


def _a_request_ended_with(get: Any, path: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [made.args[0] for made in get.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(f"Expected a request ending [{path}], got {addressed}")

        return True

    return assertion


def _the_request_named_the_ref(get: Any, ref: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        named = get.call_args.kwargs.get("params", {}).get(THE_REF_PARAMETER)

        if named != ref:
            raise AssertionError(f"Expected the read at ref [{ref}], got [{named}].")

        return True

    return assertion


def _a_difference_between(base: str, head: str) -> Assertion[SourceDifference]:
    def assertion(difference: SourceDifference) -> bool:
        if (difference.base, difference.head) != (base, head):
            raise AssertionError(
                f"Expected a difference from [{base}] to [{head}], got one from "
                f"[{difference.base}] to [{difference.head}]."
            )

        return True

    return assertion


def _pages_of(repository: str,
              revision: str,
              directory: str) -> Assertion[RevisionSource | None]:
    def assertion(pages: RevisionSource | None) -> bool:
        said = ((pages.repository, pages.revision_address.rsplit("/", 1)[-1], pages.directory)
                if pages is not None else None)

        if said != (repository, revision, directory):
            raise AssertionError(
                f"Expected the pages of [{repository}] at [{revision}] in [{directory}], "
                f"got [{pages}]."
            )

        return True

    return assertion


def _the_ref_written_was(post: Any, ref: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        written = [made.kwargs["json"].get(REF_FIELD) for made in post.call_args_list
                   if made.args[0].endswith("/git/refs")]

        if written != [ref]:
            raise AssertionError(f"Expected the one ref written to be [{ref}], got {written}")

        return True

    return assertion


def _the_proposal_asked_was(post: Any,
                            *,
                            head: str,
                            base: str,
                            title: str,
                            body: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        asked = [tuple(made.kwargs["json"].get(field)
                       for field in (HEAD_FIELD, BASE_FIELD, TITLE_FIELD, BODY_FIELD))
                 for made in post.call_args_list]

        if asked != [(head, base, title, body)]:
            raise AssertionError(
                f"Expected one proposal from [{head}] onto [{base}] titled [{title}] "
                f"saying [{body}], got {asked}"
            )

        return True

    return assertion
