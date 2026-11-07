"""A write to GitHub, made again where GitHub failed it for a moment.

A pull request Code-Fix had written was reported as one that could not be
proposed because GitHub answered 500, once, during an incident of its own. A
server's passing fault is no refusal: the write is made again, a few times and
a little apart, as configured. What the repository refused - a 4xx - is made
once, since asking again gets the same answer.

A failure can come back for a write the server carried out, and making it again
is then refused as one that already exists. So before each retry the write is
looked for, and one that landed is the answer.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import call, create_autospec

import httpx2
import pytest
from argus_testkit.assertions import (
    Assertion,
    all_of,
    an_error_was_raised,
    the_answer_was,
)
from argus_testkit.scenario import Scenario, attempting
from write_mcp_server.github_writes import said_of, with_retries

SOME_ANSWER = "some answer"
SOME_LANDED_ANSWER = "some answer that landed"
DONT_CARE_WAIT_MS = 0


@pytest.mark.unit
@pytest.mark.parametrize("failure", [
    pytest.param(lambda: _github_answered(500), id="a-500"),
    pytest.param(lambda: _github_answered(503), id="a-503"),
    pytest.param(lambda: httpx2.ConnectError("connection reset"), id="never-reached")
])
def test_a_write_github_failed_for_a_moment_is_made_again(failure: Any) -> None:
    write = _a_write(failure(), SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=2, wait_ms=DONT_CARE_WAIT_MS,
                                   sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, 2)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("status_code", [403, 404, 422])
def test_a_write_the_repository_refused_is_made_once(status_code: int) -> None:
    # Asked again, a refusal is refused again.
    write = _a_write(_github_answered(status_code), SOME_ANSWER)

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=2,
                                              wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep))) \
        .then(
            all_of(
                an_error_was_raised(httpx2.HTTPStatusError),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_write_github_keeps_failing_is_made_once_more_per_retry_and_fails_as_github_did() -> None:
    # The count is of retries - tries after the first - so two retries are
    # three tries in all.
    write = _a_write(*[_github_answered(500)] * 5)

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=2,
                                              wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep))) \
        .then(
            all_of(
                an_error_was_raised(httpx2.HTTPStatusError),
                _made(write, 3)
            )
        )


@pytest.mark.unit
def test_a_write_with_no_retries_configured_is_made_once() -> None:
    write = _a_write(_github_answered(500), SOME_ANSWER)

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=0,
                                              wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep))) \
        .then(
            all_of(
                an_error_was_raised(httpx2.HTTPStatusError),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_each_retry_waits_the_time_configured_before_it() -> None:
    write = _a_write(*[_github_answered(500)] * 3)

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=2, wait_ms=200,
                                              sleep=write.sleep))) \
        .then(
            _waited(write, [0.2, 0.2])
        )


@pytest.mark.unit
def test_a_write_that_landed_despite_failing_is_not_made_again() -> None:
    write = _a_write(_github_answered(500), SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=2, wait_ms=DONT_CARE_WAIT_MS,
                                   landed=lambda: SOME_LANDED_ANSWER, sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_LANDED_ANSWER),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_write_not_found_to_have_landed_is_made_again() -> None:
    write = _a_write(_github_answered(500), SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=2, wait_ms=DONT_CARE_WAIT_MS,
                                   landed=lambda: None, sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, 2)
            )
        )


@pytest.mark.unit
def test_a_write_that_could_not_be_looked_for_is_made_again() -> None:
    # The look is a request to the same GitHub, and fails with it. Made again,
    # a write that did land is refused as one that exists - a failure, never a
    # second pull request or a second branch.
    write = _a_write(_github_answered(500), SOME_ANSWER)

    def looking_fails() -> str | None:
        raise httpx2.ConnectError("connection reset")

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=2, wait_ms=DONT_CARE_WAIT_MS,
                                   landed=looking_fails, sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, 2)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("failure", "said"), [
    pytest.param(lambda: _github_answered(500), "GitHub answered 500 Internal Server Error",
                 id="an-answer"),
    pytest.param(lambda: httpx2.ConnectError("connection reset"), "connection reset",
                 id="no-answer"),
    pytest.param(lambda: httpx2.ReadTimeout(""), "ReadTimeout", id="no-words")
])
def test_a_failed_write_is_said_as_github_answered_it(failure: Any, said: str) -> None:
    # The HTTP library's own sentence names the address a second time and
    # sends a reader to a Mozilla page about status codes. What failed is
    # GitHub's answer, where there was one.
    Scenario() \
        .when(lambda: said_of(failure())) \
        .then(
            the_answer_was(said)
        )


def _github_answered(status_code: int) -> httpx2.HTTPStatusError:
    request = httpx2.Request("POST", "https://api.github.invalid/repos/dont-care/dont-care/pulls")

    return httpx2.HTTPStatusError(
        f"dont care {status_code}",
        request=request,
        response=httpx2.Response(status_code=status_code, request=request)
    )


class _Write:
    def __init__(self, *answers: Any) -> None:
        self.attempt: Any = create_autospec(lambda: None, side_effect=list(answers))
        self.sleep: Any = create_autospec(time.sleep)


def _a_write(*answers: Any) -> _Write:
    """A write answering each try with the next of `answers` - an exception is
    raised, anything else returned."""
    return _Write(*answers)


def _made(write: _Write, times: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if write.attempt.call_count != times:
            raise AssertionError(
                f"Expected the write made {times} times, it was made {write.attempt.call_count}."
            )

        return True

    return assertion


def _waited(write: _Write, seconds: list[float]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if write.sleep.call_args_list != [call(each) for each in seconds]:
            raise AssertionError(
                f"Expected waits of {seconds} seconds, "
                f"got {[made.args for made in write.sleep.call_args_list]}."
            )

        return True

    return assertion
