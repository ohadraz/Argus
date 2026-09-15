"""Putting a proposed fix on a branch of its own (spec §7.4, §13).

The half of Code-Fix's outward act that touches code. It writes to a branch and
only ever to a branch: `main` is not reachable from here, so the worst a wrong
patch can do is exist somewhere nobody is running.

It writes whatever the fix names, tests included. A fix that comes with the test
that exposes the bug is the fix a person can trust, so nothing here second-
guesses which paths a patch may touch - what stops a bad change is that it lands
on a branch nobody runs, and that a person has to merge it.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from write_mcp_server.branching import (
    BranchNotWritten,
    commit_to_new_branch,
)
from write_mcp_server.pull_requests import RepositoryWriteSettings

DONT_CARE_BRANCH = "argus/dont-care"
DONT_CARE_BASE = "main"
DONT_CARE_MESSAGE = "dont care message"
DONT_CARE_FILES = {"src/io_shop/spend_summary.py": "dont care content"}

SOME_BASE_HEAD = "9f4c1e7b2a3d5c8e1f0b6a4d2c9e7b5a3f1d8c6e"


@pytest.mark.unit
def test_a_fix_gets_a_branch_of_its_own_off_the_one_it_fixes() -> None:
    # Off the base's head rather than off a default: the fix has to apply to
    # the code that is actually deployed, and a branch cut from somewhere else
    # proposes a change against a repository nobody is running.
    some_branch = "argus/fix-monthly-spend-divisor"
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=some_branch,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _a_branch_was_created(repository, some_branch, at=SOME_BASE_HEAD)
            )
        )


@pytest.mark.unit
def test_the_head_it_branches_from_is_read_from_the_base_branch() -> None:
    some_base = "main"
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=some_base,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _a_request_was_made_to(
                    repository.get, f"/git/ref/heads/{some_base}"
                )
            )
        )


@pytest.mark.unit
def test_every_file_in_the_fix_is_written_to_the_new_branch() -> None:
    # Named explicitly on each write. The Contents API defaults to the
    # repository's default branch when no branch is given, so a patch that
    # forgot to say would land on `main` - the one outcome this module exists
    # to make impossible.
    some_branch = "argus/fix-monthly-spend-divisor"
    some_files = {
        "src/io_shop/spend_summary.py": "the patched module",
        "tests/io_shop/test_regression.py": "the regression test it brings"
    }
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=some_branch,
                base_branch=DONT_CARE_BASE,
                files=some_files,
                message=DONT_CARE_MESSAGE,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _every_write_named_the_branch(repository, some_branch),
                _a_file_was_written(
                    repository,
                    "src/io_shop/spend_summary.py",
                    content="the patched module"
                ),
                _a_file_was_written(
                    repository,
                    "tests/io_shop/test_regression.py",
                    content="the regression test it brings"
                )
            )
        )


@pytest.mark.unit
def test_the_fix_is_committed_under_the_message_it_was_given() -> None:
    some_message = "fix: the monthly figure divides by an empty month"
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=some_message,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _every_write_was_committed_as(repository, some_message)
            )
        )


@pytest.mark.unit
def test_rewriting_a_file_that_exists_replaces_the_version_it_read() -> None:
    # The Contents API refuses an update that does not name the blob it is
    # replacing. Without it, every patch to an existing file - which is what a
    # bug fix always is - would be rejected.
    some_existing_blob = "abc123def456"
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.get.side_effect = [
        _a_ref_answer(SOME_BASE_HEAD),
        _a_file_answer(some_existing_blob)
    ]

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _the_write_replaced_blob(repository, some_existing_blob)
            )
        )


@pytest.mark.unit
def test_a_file_the_fix_adds_is_written_without_replacing_anything() -> None:
    # A fix may bring a regression test that did not exist. Sending a blob sha
    # for a file with no previous version is what the API rejects, so the
    # absence has to be real rather than an empty string.
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.get.side_effect = [
        _a_ref_answer(SOME_BASE_HEAD),
        _a_file_that_is_not_there()
    ]

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files={"tests/io_shop/test_new.py": "a test that is new"},
                message=DONT_CARE_MESSAGE,
                settings=some_settings(),
                get=repository.get,
                post=repository.post,
                put=repository.put
            )
        ) \
        .then(
            all_of(
                _the_write_replaced_nothing(repository)
            )
        )


@pytest.mark.unit
def test_a_repository_that_refuses_the_branch_is_not_reported_as_written() -> None:
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.post.return_value = httpx.Response(
        status_code=422,
        json={"message": "Reference already exists"},
        request=httpx.Request("POST", "http://github.invalid/")
    )

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten)
            )
        )


@pytest.mark.unit
def test_an_unreachable_repository_is_not_reported_as_written() -> None:
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.get.side_effect = httpx.ConnectError("connection refused")

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten)
            )
        )


@pytest.mark.unit
def test_a_file_the_repository_refuses_is_not_reported_as_written() -> None:
    # The failure that arrives late: the branch was created, and then a write
    # onto it was rejected. The branch is left behind - there is no undoing a
    # push from here - but the caller is told, so nothing opens a pull request
    # for a patch that is not all there.
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.put.return_value = httpx.Response(
        status_code=409,
        json={"message": "is at 1a2b3c but expected 4d5e6f"},
        request=httpx.Request("PUT", "http://github.invalid/")
    )

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten)
            )
        )


def _a_branch_was_created(repository: _Repository,
                          branch: str,
                          *,
                          at: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = repository.post.call_args.kwargs["json"]
        expected_ref = f"refs/heads/{branch}"

        if body.get("ref") != expected_ref:
            raise AssertionError(
                f"Expected a branch created as [{expected_ref}], "
                f"got [{body.get('ref')}]."
            )

        if body.get("sha") != at:
            raise AssertionError(
                f"Expected the branch cut at [{at}], got [{body.get('sha')}]."
            )

        return True

    return assertion


def _a_request_was_made_to(call: Any, path: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [made.args[0] for made in call.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def _every_write_named_the_branch(repository: _Repository,
                                  branch: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        named = [
            written.kwargs["json"].get("branch")
            for written in repository.put.call_args_list
        ]

        if not named:
            raise AssertionError("Expected files to be written, none were.")

        if any(said != branch for said in named):
            raise AssertionError(
                f"Expected every write to name branch [{branch}], got {named}."
            )

        return True

    return assertion


def _a_file_was_written(repository: _Repository,
                        path: str,
                        *,
                        content: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        for written in repository.put.call_args_list:
            if not written.args[0].endswith(f"/contents/{path}"):
                continue

            sent = base64.b64decode(written.kwargs["json"]["content"]).decode()

            if sent != content:
                raise AssertionError(
                    f"Expected [{path}] written as [{content!r}], got [{sent!r}]."
                )

            return True

        raise AssertionError(f"Expected [{path}] to be written, it was not.")

    return assertion


def _every_write_was_committed_as(repository: _Repository,
                                  message: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = [
            written.kwargs["json"].get("message")
            for written in repository.put.call_args_list
        ]

        if not said or any(carried != message for carried in said):
            raise AssertionError(
                f"Expected every write committed as [{message!r}], got {said}."
            )

        return True

    return assertion


def _the_write_replaced_blob(repository: _Repository, blob: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        replaced = repository.put.call_args.kwargs["json"].get("sha")

        if replaced != blob:
            raise AssertionError(
                f"Expected the write to replace blob [{blob}], got [{replaced}]."
            )

        return True

    return assertion


def _the_write_replaced_nothing(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = repository.put.call_args.kwargs["json"]

        if "sha" in body:
            raise AssertionError(
                f"Expected a new file to name no blob, it named [{body['sha']}]."
            )

        return True

    return assertion


def _nothing_was_written(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if repository.put.call_args_list or repository.post.call_args_list:
            raise AssertionError(
                f"Expected nothing to be written: "
                f"{repository.post.call_count} branch calls, "
                f"{repository.put.call_count} file writes."
            )

        return True

    return assertion


def _writing_to(repository: _Repository) -> Any:
    """One call, for the tests about how it fails rather than what it sent."""
    return commit_to_new_branch(
        branch=DONT_CARE_BRANCH,
        base_branch=DONT_CARE_BASE,
        files=DONT_CARE_FILES,
        message=DONT_CARE_MESSAGE,
        settings=some_settings(),
        get=repository.get,
        post=repository.post,
        put=repository.put
    )


def _a_ref_answer(head: str) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"object": {"sha": head}},
        request=httpx.Request("GET", "http://github.invalid/")
    )


def _a_file_answer(blob: str) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"sha": blob},
        request=httpx.Request("GET", "http://github.invalid/")
    )


def _a_file_that_is_not_there() -> httpx.Response:
    return httpx.Response(
        status_code=404,
        json={"message": "Not Found"},
        request=httpx.Request("GET", "http://github.invalid/")
    )


class _Repository:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx.get)
        self.post: Any = create_autospec(httpx.post)
        self.put: Any = create_autospec(httpx.put)


def a_repository_whose_head_is(head: str) -> _Repository:
    """A repository that answers every call successfully.

    The ref read answers first and the file reads after it, so a test that cares
    which blob a write replaced sets `get.side_effect` explicitly. One that does
    not gets a file already there, which is what a bug fix patches.
    """
    repository = _Repository()
    repository.get.return_value = _a_ref_answer(head)
    repository.post.return_value = httpx.Response(
        status_code=201,
        json={"ref": f"refs/heads/{DONT_CARE_BRANCH}"},
        request=httpx.Request("POST", "http://github.invalid/")
    )
    repository.put.return_value = httpx.Response(
        status_code=201,
        json={"commit": {"sha": "written"}},
        request=httpx.Request("PUT", "http://github.invalid/")
    )

    return repository


def some_settings(api_url: str = "https://api.github.invalid",
                  repository: str = "dont-care/dont-care",
                  token: str = "ghp_dont-care-token") -> RepositoryWriteSettings:
    """The same slice the pull request tool writes under - one repository, one
    credential, and both halves of Code-Fix's act reaching it."""
    return RepositoryWriteSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_token=token
    )
