"""Putting a proposed fix on a branch of its own (spec §7.4, §13).

The half of Code-Fix's outward act that touches code. It writes to a branch and
only ever to a branch: `main` is not reachable from here, so the worst a wrong
patch can do is exist somewhere nobody is running.

The fix arrives as **one commit**. Every file it names goes into a single tree
written on top of the base, and the branch is created last, pointing at the
finished commit - so a reviewer reads one change rather than one commit per
file, and a patch is on a branch whole or not there at all.

It writes whatever the fix names, tests included. A fix that comes with the test
that exposes the bug is the fix a person can trust, so nothing here second-
guesses which paths a patch may touch - what stops a bad change is that it lands
on a branch nobody runs, and that a person has to merge it.
"""

from __future__ import annotations

from collections.abc import Callable
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

from write_mcp_server_test.framework.settings import some_repository_settings

DONT_CARE_BRANCH = "argus/dont-care"
DONT_CARE_BASE = "main"
DONT_CARE_MESSAGE = "dont care message"
DONT_CARE_FILES = {"src/io_shop/spend_summary.py": "dont care content"}

SOME_BASE_HEAD = "9f4c1e7b2a3d5c8e1f0b6a4d2c9e7b5a3f1d8c6e"
SOME_BASE_TREE = "1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4"
SOME_WRITTEN_TREE = "7e6d5c4b3a291807f6e5d4c3b2a190817263f5e4"
SOME_WRITTEN_COMMIT = "3f1d8c6e9f4c1e7b2a3d5c8e1f0b6a4d2c9e7b5a"

TREES = "/git/trees"
COMMITS = "/git/commits"
REFS = "/git/refs"

# What the two doubles are: a call answered by the URL it was given. Spelled out
# rather than left as `Any`, because the wrappers below hand one answer straight
# back - and `Any` returned from a function promising a `Response` is the one
# thing mypy cannot check for you.
_Answering = Callable[..., httpx.Response]


@pytest.mark.unit
def test_the_whole_fix_arrives_as_one_commit() -> None:
    # A reviewer reads a fix, not a file at a time. Writing each path on its own
    # made a commit per file - three files, three commits, all carrying the same
    # message - so the change had to be read as a diff against a base rather
    # than as the thing it is.
    some_files = {
        "src/io_shop/spend_summary.py": "the patched module",
        "tests/io_shop/test_spend_summary.py": "the regression test it brings",
        "tests/io_shop/test_account_page.py": "the page test it touched"
    }
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=some_files,
                message=DONT_CARE_MESSAGE,
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _exactly_one_commit_was_written(repository)
            )
        )


@pytest.mark.unit
def test_a_fix_gets_a_branch_of_its_own_pointing_at_the_commit_it_became() -> None:
    some_branch = "argus/fix-monthly-spend-divisor"
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=some_branch,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _a_branch_was_created(repository, some_branch, at=SOME_WRITTEN_COMMIT)
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
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
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
def test_the_commit_sits_on_top_of_the_code_it_fixes() -> None:
    # On top of the base rather than beside it, in both halves: the tree is
    # written over the base's own tree, so files the fix did not name survive,
    # and the commit names the base as its parent. A commit with no parent is a
    # root commit, which shares no history with the branch it is proposed
    # against and cannot be merged into it.
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_tree_was_written_over(repository, SOME_BASE_TREE),
                _the_commit_was_a_child_of(repository, SOME_BASE_HEAD),
                _the_commit_points_at_the_tree(repository, SOME_WRITTEN_TREE)
            )
        )


@pytest.mark.unit
def test_every_file_in_the_fix_is_in_the_tree_the_commit_points_at() -> None:
    some_files = {
        "src/io_shop/spend_summary.py": "the patched module",
        "tests/io_shop/test_regression.py": "the regression test it brings"
    }
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=some_files,
                message=DONT_CARE_MESSAGE,
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
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
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_commit_was_written_as(repository, some_message)
            )
        )


@pytest.mark.unit
def test_the_branch_appears_only_once_the_commit_is_whole() -> None:
    # Nothing anyone can reach exists until the last call: a tree and a commit
    # are unreachable objects until a ref points at one. A branch created first
    # and written to file by file can be found half-patched, and a pull request
    # opened from it proposes a change nobody wrote.
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)

    Scenario() \
        .when(
            lambda: commit_to_new_branch(
                branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                files=DONT_CARE_FILES,
                message=DONT_CARE_MESSAGE,
                settings=some_repository_settings(),
                get=repository.get,
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_branch_was_created_last(repository)
            )
        )


@pytest.mark.unit
def test_a_tree_the_repository_refuses_leaves_no_branch_behind() -> None:
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.post.side_effect = _refusing(
        TREES, status_code=422, saying="tree entry is not valid"
    )

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten),
                _no_branch_was_created(repository)
            )
        )


@pytest.mark.unit
def test_a_commit_the_repository_refuses_leaves_no_branch_behind() -> None:
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.post.side_effect = _refusing(
        COMMITS, status_code=422, saying="parents are not valid"
    )

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten),
                _no_branch_was_created(repository)
            )
        )


@pytest.mark.unit
def test_a_repository_that_refuses_the_branch_is_not_reported_as_written() -> None:
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.post.side_effect = _refusing(
        REFS, status_code=422, saying="Reference already exists"
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
def test_a_base_whose_commit_cannot_be_read_is_not_reported_as_written() -> None:
    # The tree has to be written over the base's own, so a base commit that
    # cannot be read is not a detail to work around: a tree written over
    # nothing would propose a repository containing only the patched files.
    repository = a_repository_whose_head_is(SOME_BASE_HEAD)
    repository.get.side_effect = _reading_but_refusing_the_commit(SOME_BASE_HEAD)

    Scenario() \
        .when(attempting(lambda: _writing_to(repository))) \
        .then(
            all_of(
                an_error_was_raised(BranchNotWritten),
                _no_branch_was_created(repository)
            )
        )


def _exactly_one_commit_was_written(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        written = _posted(repository, COMMITS)

        if len(written) != 1:
            raise AssertionError(
                f"Expected the fix to arrive as one commit, got {len(written)}: "
                f"{[said.get('message') for said in written]}."
            )

        return True

    return assertion


def _a_branch_was_created(repository: _Repository,
                          branch: str,
                          *,
                          at: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, REFS), "branch")
        expected_ref = f"refs/heads/{branch}"

        if body.get("ref") != expected_ref:
            raise AssertionError(
                f"Expected a branch created as [{expected_ref}], "
                f"got [{body.get('ref')}]."
            )

        if body.get("sha") != at:
            raise AssertionError(
                f"Expected the branch pointing at [{at}], got [{body.get('sha')}]."
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


def _the_tree_was_written_over(repository: _Repository, base_tree: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, TREES), "tree")

        if body.get("base_tree") != base_tree:
            raise AssertionError(
                f"Expected the tree written over [{base_tree}], "
                f"got [{body.get('base_tree')}]."
            )

        return True

    return assertion


def _the_commit_was_a_child_of(repository: _Repository, parent: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, COMMITS), "commit")

        if body.get("parents") != [parent]:
            raise AssertionError(
                f"Expected the commit's parents [{[parent]}], got {body.get('parents')}."
            )

        return True

    return assertion


def _the_commit_points_at_the_tree(repository: _Repository, tree: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, COMMITS), "commit")

        if body.get("tree") != tree:
            raise AssertionError(
                f"Expected the commit pointing at tree [{tree}], got [{body.get('tree')}]."
            )

        return True

    return assertion


def _a_file_was_written(repository: _Repository,
                        path: str,
                        *,
                        content: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, TREES), "tree")
        entries = body.get("tree", [])

        for entry in entries:
            if entry.get("path") != path:
                continue

            if entry.get("content") != content:
                raise AssertionError(
                    f"Expected [{path}] written as [{content!r}], "
                    f"got [{entry.get('content')!r}]."
                )

            if entry.get("mode") != "100644":
                raise AssertionError(
                    f"Expected [{path}] written as an ordinary file [100644], "
                    f"got mode [{entry.get('mode')}]."
                )

            return True

        raise AssertionError(
            f"Expected [{path}] in the tree, got {[said.get('path') for said in entries]}."
        )

    return assertion


def _the_commit_was_written_as(repository: _Repository, message: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _the_one(_posted(repository, COMMITS), "commit")

        if body.get("message") != message:
            raise AssertionError(
                f"Expected the commit message [{message!r}], "
                f"got [{body.get('message')!r}]."
            )

        return True

    return assertion


def _the_branch_was_created_last(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [made.args[0] for made in repository.post.call_args_list]

        if not addressed or not addressed[-1].endswith(REFS):
            raise AssertionError(
                f"Expected the branch created last, the writes were {addressed}."
            )

        return True

    return assertion


def _no_branch_was_created(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        created = _posted(repository, REFS)

        if created:
            raise AssertionError(
                f"Expected no branch to be created, {len(created)} was: {created}."
            )

        return True

    return assertion


def _posted(repository: _Repository, to: str) -> list[dict[str, Any]]:
    """Every body sent to one endpoint, in the order it was sent."""
    return [
        made.kwargs["json"]
        for made in repository.post.call_args_list
        if made.args[0].endswith(to)
    ]


def _the_one(written: list[dict[str, Any]], what: str) -> dict[str, Any]:
    """The single body an endpoint was sent, or a failure naming how many it got.

    Most of what this module does happens exactly once, so "which one did you
    mean" is never the right question - a second tree or a second commit is the
    defect itself, and reading `[0]` would hide it.
    """
    if len(written) != 1:
        raise AssertionError(f"Expected one {what} to be written, got {len(written)}.")

    return written[0]


def _writing_to(repository: _Repository) -> Any:
    """One call, for the tests about how it fails rather than what it sent."""
    return commit_to_new_branch(
        branch=DONT_CARE_BRANCH,
        base_branch=DONT_CARE_BASE,
        files=DONT_CARE_FILES,
        message=DONT_CARE_MESSAGE,
        settings=some_repository_settings(),
        get=repository.get,
        post=repository.post
    )


def _an_answer(body: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("GET", "http://github.invalid/")
    )


def _reading(head: str) -> _Answering:
    """Answers the two reads by the URL asked for rather than by their order.

    A list of canned responses has to be re-counted every time the module reads
    one more thing, and re-counted wrongly it passes a ref answer off as a
    commit - which is a green test for code that cannot work.
    """
    def answer(url: str, **_: Any) -> httpx.Response:
        if "/git/ref/heads/" in url:
            return _an_answer({"object": {"sha": head}})

        if f"/git/commits/{head}" in url:
            return _an_answer({"sha": head, "tree": {"sha": SOME_BASE_TREE}})

        raise AssertionError(f"Nothing here reads [{url}].")

    return answer


def _reading_but_refusing_the_commit(head: str) -> _Answering:
    answering = _reading(head)

    def answer(url: str, **called: Any) -> httpx.Response:
        if f"/git/commits/{head}" in url:
            return _an_answer({"message": "Not Found"}, status_code=404)

        return answering(url, **called)

    return answer


def _writing() -> _Answering:
    """Answers the three writes by the URL written to, for the same reason."""
    def answer(url: str, **_: Any) -> httpx.Response:
        if url.endswith(TREES):
            return _an_answer({"sha": SOME_WRITTEN_TREE}, status_code=201)

        if url.endswith(COMMITS):
            return _an_answer({"sha": SOME_WRITTEN_COMMIT}, status_code=201)

        if url.endswith(REFS):
            return _an_answer(
                {"ref": f"refs/heads/{DONT_CARE_BRANCH}"}, status_code=201
            )

        raise AssertionError(f"Nothing here writes to [{url}].")

    return answer


def _refusing(endpoint: str, *, status_code: int, saying: str) -> _Answering:
    """A repository that answers every write but the one endpoint named."""
    answering = _writing()

    def answer(url: str, **called: Any) -> httpx.Response:
        if url.endswith(endpoint):
            return _an_answer({"message": saying}, status_code=status_code)

        return answering(url, **called)

    return answer


class _Repository:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx.get)
        self.post: Any = create_autospec(httpx.post)


def a_repository_whose_head_is(head: str) -> _Repository:
    """A repository that answers every call successfully."""
    repository = _Repository()
    repository.get.side_effect = _reading(head)
    repository.post.side_effect = _writing()

    return repository
