"""A pull request Argus opened, by the name Argus gives it wherever it is
mentioned."""

from __future__ import annotations

import pytest
from argus_core.models import OpenedPullRequest
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
def test_a_pull_request_is_named_as_github_names_it() -> None:
    # One name wherever it is mentioned: the summary said "pull request #1"
    # where every other mention said "PR #1", and only those led to it.
    Scenario() \
        .given(
            some_pull_request := OpenedPullRequest(number=7,
                                                   url="https://github.invalid/pull/7",
                                                   branch="dont care")
        ) \
        .when(
            lambda: some_pull_request.name
        ) \
        .then(
            the_answer_was("PR #7")
        )
