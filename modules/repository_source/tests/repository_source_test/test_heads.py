"""Where a branch currently points (spec §11).

What the catch-up pass asks when nothing has told it anything. A push webhook
records where the repository went, but a deployment that has never received a
delivery - no tunnel, a webhook nobody configured, a secret that does not match
- has no record at all, and an index that waited to be told would then never be
built. Asking is what makes the catch-up pass level-triggered rather than
edge-triggered wearing a reconciler's name.

One call, one string. It is deliberately not a way to read anything: the
answer is a commit id, and everything that reads code at that commit is
elsewhere in this module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit.assertions import Assertion, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from repository_source import RepositoryUnreadable
from repository_source.heads import the_head_of

from repository_source_test.framework.settings import some_settings

THE_DEPLOYED_BRANCH = "main"
THE_COMMIT_IT_POINTS_AT = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

DONT_CARE_BRANCH = "main"


@pytest.mark.unit
def test_the_commit_a_branch_points_at_is_answered() -> None:
    repository = a_branch_at(THE_COMMIT_IT_POINTS_AT)

    Scenario() \
        .when(
            lambda: the_head_of(
                DONT_CARE_BRANCH, some_settings(), get=repository
            )
        ) \
        .then(_the_head_is(THE_COMMIT_IT_POINTS_AT))


@pytest.mark.unit
def test_a_branch_is_asked_for_as_a_branch_and_not_as_a_name() -> None:
    # A tag and a branch can carry the same name, and the API takes either
    # under a bare ref. Asked without saying which, a repository holding a
    # `main` tag from some release would have the index built at whatever that
    # tag froze rather than at what is deployed.
    repository = a_branch_at(THE_COMMIT_IT_POINTS_AT)

    Scenario() \
        .when(
            lambda: the_head_of(
                THE_DEPLOYED_BRANCH, some_settings(), get=repository
            )
        ) \
        .then(_the_request_ended_with(
            repository, f"/commits/heads/{THE_DEPLOYED_BRANCH}"
        ))


@pytest.mark.unit
def test_a_branch_that_could_not_be_read_is_refused_rather_than_answered() -> None:
    # Nothing sensible is available to answer instead. An empty string would
    # be compared against the indexed commit, differ from it, and have the
    # catch-up pass try to build an index at a commit that does not exist - every
    # pass, forever.
    refused = create_autospec(httpx.get)
    refused.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: the_head_of(
                    DONT_CARE_BRANCH, some_settings(), get=refused
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


def _the_head_is(sha: str) -> Assertion[str]:
    def assertion(answered: str) -> bool:
        if answered != sha:
            raise AssertionError(f"Expected the head at [{sha}], got [{answered}].")

        return True

    return assertion


def _the_request_ended_with(repository: Any, path: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        addressed = [made.args[0] for made in repository.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def a_branch_at(sha: str) -> Any:
    """GitHub's answer for a branch: the commit it points at, among much else."""
    repository = create_autospec(httpx.get)
    repository.return_value = httpx.Response(
        status_code=200,
        json={"sha": sha, "commit": {"message": "a commit somebody pushed"}},
        request=httpx.Request("GET", "http://github.invalid/")
    )

    return repository
