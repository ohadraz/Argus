"""Whether a branch holds a commit - whether the commit is in its history.

What Code-Fix is told before it reads anything. It reads one branch, and the
revision that was running when the incident began may never have been merged
into it: deployed from a branch of its own, so the files Code-Fix opens are not
the files that ran. Said where it is true and only there - a caveat on every
incident would be one on the ordinary case, where the branch holds what ran.

GitHub answers it as part of a comparison, from where the second commit stands
to the first: ahead of it or the same commit, and the first is in its history;
behind it or on another line from it, and it is not.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_testkit.assertions import Assertion, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from repository_source import RepositoryUnreadable
from repository_source.holding import the_branch_holds

from repository_source_test.framework.settings import some_settings

THE_BRANCH_READ = "main"
THE_REVISION_THAT_RAN = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"

DONT_CARE_BRANCH = THE_BRANCH_READ
DONT_CARE_REVISION = THE_REVISION_THAT_RAN


@pytest.mark.unit
def test_a_revision_the_branch_has_moved_past_is_held() -> None:
    compared = a_comparison_standing("ahead")

    Scenario() \
        .when(
            lambda: the_branch_holds(
                DONT_CARE_BRANCH, DONT_CARE_REVISION, some_settings(), get=compared
            )
        ) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_the_revision_the_branch_points_at_is_held() -> None:
    compared = a_comparison_standing("identical")

    Scenario() \
        .when(
            lambda: the_branch_holds(
                DONT_CARE_BRANCH, DONT_CARE_REVISION, some_settings(), get=compared
            )
        ) \
        .then(_the_answer_is(True))


@pytest.mark.unit
def test_a_revision_deployed_from_another_branch_is_not_held() -> None:
    # THE ONE THE QUESTION EXISTS FOR. A revision on a branch that was never
    # merged shares history with the one read, and has commits of its own the
    # branch has never seen.
    compared = a_comparison_standing("diverged")

    Scenario() \
        .when(
            lambda: the_branch_holds(
                DONT_CARE_BRANCH, DONT_CARE_REVISION, some_settings(), get=compared
            )
        ) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_a_revision_the_branch_has_not_reached_yet_is_not_held() -> None:
    compared = a_comparison_standing("behind")

    Scenario() \
        .when(
            lambda: the_branch_holds(
                DONT_CARE_BRANCH, DONT_CARE_REVISION, some_settings(), get=compared
            )
        ) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_the_comparison_asked_for_runs_from_the_revision_to_the_branch() -> None:
    # Ordered, and it matters: reversed, "ahead" would mean the revision has
    # moved past the branch - the opposite of holding it.
    compared = a_comparison_standing("ahead")

    Scenario() \
        .when(
            lambda: the_branch_holds(
                THE_BRANCH_READ, THE_REVISION_THAT_RAN, some_settings(), get=compared
            )
        ) \
        .then(_the_request_ended_with(
            compared, f"/compare/{THE_REVISION_THAT_RAN}...{THE_BRANCH_READ}"
        ))


@pytest.mark.unit
def test_a_comparison_that_could_not_be_made_raises() -> None:
    # Not `False`. Told that what ran is not on the branch, Code-Fix hedges
    # every claim it makes about the code - and nobody established that.
    refused = create_autospec(httpx2.get)
    refused.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: the_branch_holds(
                    DONT_CARE_BRANCH, DONT_CARE_REVISION, some_settings(), get=refused
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


def _the_answer_is(expected: bool) -> Assertion[bool]:
    def assertion(held: bool) -> bool:
        if held is not expected:
            raise AssertionError(
                f"Expected the branch {'to' if expected else 'not to'} hold the "
                f"revision, and the answer was {held}."
            )

        return True

    return assertion


def _the_request_ended_with(compared: Any, path: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        addressed = [made.args[0] for made in compared.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def a_comparison_standing(status: str) -> Any:
    """GitHub's answer for two commits, saying how the second stands to the
    first."""
    compared = create_autospec(httpx2.get)
    compared.return_value = httpx2.Response(
        status_code=200,
        json={"status": status, "ahead_by": 0, "behind_by": 0, "files": []},
        request=httpx2.Request("GET", "http://github.invalid/")
    )

    return compared
