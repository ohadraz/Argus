"""A write to GitHub, made again where GitHub failed it for a moment.

A pull request Code-Fix had written was reported as one that could not be
proposed because GitHub answered 500, once, during an incident of its own. A
server's passing fault is no refusal: the write is made again, a few times and
a little apart, as configured. What the repository refused - a 4xx - is made
once, since asking again gets the same answer.

A failure can come back for a write the server carried out, and making it again
is then refused as one that already exists. So before each try the write is
looked for, and one that landed is the answer - before the first try too,
because the first try of this tool can be the second asking of it: a call whose
answer was lost on its way back to the walk is asked again over a new session,
and by then the write is there. And once more before a failure is raised, since
a refusal can be over the write itself and a last try GitHub failed can have
landed. A look that finds the place taken by other work is an answer too, and
is raised as it came.
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
from write_mcp_server.github_writes import TakenByOtherWork, said_of, with_retries

from write_mcp_server_test.framework.github import A_BRANCH_THAT_EXISTS_STATUS

SOME_ANSWER = "some answer"
SOME_LANDED_ANSWER = "some answer that landed"
DONT_CARE_WAIT_MS = 0
# Retries - tries after the first - where how many matters to the case, and
# where it does not.
SOME_RETRIES = 2
DONT_CARE_RETRIES = 2
# A wait configured before each retry, and the same wait as the sleep is asked
# for it - in seconds.
SOME_WAIT_MS = 200
MILLISECONDS_IN_A_SECOND = 1000
SOME_WAIT_SECONDS = SOME_WAIT_MS / MILLISECONDS_IN_A_SECOND
# A request that never reached GitHub, in the HTTP library's words.
SOME_TRANSPORT_FAILURE = "connection reset"
# What a look says of the place a write would land, taken by other work.
DONT_CARE_WHAT_THE_LOOK_SAID = "the place is taken by other work"


@pytest.mark.unit
@pytest.mark.parametrize("failure", [
    pytest.param(lambda: _github_answered(500), id="a-500"),
    pytest.param(lambda: _github_answered(503), id="a-503"),
    pytest.param(lambda: httpx2.ConnectError(SOME_TRANSPORT_FAILURE), id="never-reached")
])
def test_a_write_github_failed_for_a_moment_is_made_again(failure: Any) -> None:
    some_answers = [failure(), SOME_ANSWER]
    write = _a_write(*some_answers)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, len(some_answers))
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("status_code", [403, 404, 422])
def test_a_write_the_repository_refused_is_made_once(status_code: int) -> None:
    # Asked again, a refusal is refused again - however many retries there are.
    write = _a_write(_github_answered(status_code), SOME_ANSWER)

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                              wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep))) \
        .then(
            all_of(
                an_error_was_raised(httpx2.HTTPStatusError),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_write_github_keeps_failing_is_made_once_more_per_retry_and_fails_as_github_did() -> None:
    # The count is of retries - tries after the first - so there is one try
    # more than there are retries. One failure more than that is staged, so the
    # count is the retries' and not the answers' running out.
    write = _a_write(*[_github_answered(500)] * (SOME_RETRIES + 2))

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                              wait_ms=DONT_CARE_WAIT_MS, sleep=write.sleep))) \
        .then(
            all_of(
                an_error_was_raised(httpx2.HTTPStatusError),
                _made(write, SOME_RETRIES + 1)
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
    write = _a_write(*[_github_answered(500)] * (SOME_RETRIES + 1))

    Scenario() \
        .when(attempting(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                              wait_ms=SOME_WAIT_MS, sleep=write.sleep))) \
        .then(
            _waited(write, [SOME_WAIT_SECONDS] * SOME_RETRIES)
        )


@pytest.mark.unit
def test_a_write_that_landed_despite_failing_is_not_made_again() -> None:
    write = _a_write(_github_answered(500), SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_found_once_made(write, SOME_LANDED_ANSWER),
                                   sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_LANDED_ANSWER),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_write_already_there_before_it_was_first_made_is_not_made() -> None:
    # The second asking of a tool whose first asking landed and whose answer
    # was lost on the way back. Made again, a branch or a pull request is
    # refused as one that exists, and a fix that was proposed is reported as
    # one that could not be.
    write = _a_write(SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=DONT_CARE_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_found(SOME_LANDED_ANSWER), sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_LANDED_ANSWER),
                _made(write, 0),
                _waited(write, [])
            )
        )


@pytest.mark.unit
def test_a_write_not_there_before_it_was_first_made_is_made_without_waiting() -> None:
    # The look before the first try is a look, not a retry: nothing failed, so
    # nothing is waited for.
    write = _a_write(SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=DONT_CARE_RETRIES,
                                   wait_ms=SOME_WAIT_MS,
                                   landed=_found(None), sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, 1),
                _waited(write, [])
            )
        )


@pytest.mark.unit
def test_a_write_that_could_not_be_looked_for_before_it_was_first_made_is_made() -> None:
    # A look that fails is no answer either way, before the first try as before
    # any other: what making it risks is a refusal, never a second pull request.
    write = _a_write(SOME_ANSWER)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=DONT_CARE_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_a_look_that_fails(), sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_write_not_found_to_have_landed_is_made_again() -> None:
    some_answers = [_github_answered(500), SOME_ANSWER]
    write = _a_write(*some_answers)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=lambda: None, sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, len(some_answers))
            )
        )


@pytest.mark.unit
def test_a_write_that_could_not_be_looked_for_is_made_again() -> None:
    # The look is a request to the same GitHub, and fails with it. Made again,
    # a write that did land is refused as one that exists - a failure, never a
    # second pull request or a second branch.
    some_answers = [_github_answered(500), SOME_ANSWER]
    write = _a_write(*some_answers)

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_a_look_that_fails(), sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_ANSWER),
                _made(write, len(some_answers))
            )
        )


@pytest.mark.unit
def test_a_refused_write_found_by_the_look_after_it_is_answered_as_made() -> None:
    # Refused as one that exists, and what exists is the write itself - landed
    # by an earlier asking a look before the first try could not find. The look
    # made before the refusal is raised finds it, and the write is answered as
    # made rather than reported as one that could not be.
    write = _a_write(_github_answered(A_BRANCH_THAT_EXISTS_STATUS))

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=DONT_CARE_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_found_once_made(write, SOME_LANDED_ANSWER),
                                   sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_LANDED_ANSWER),
                _made(write, 1)
            )
        )


@pytest.mark.unit
def test_a_last_try_github_failed_that_landed_is_answered_as_made() -> None:
    # Every try answered 500, and the last of them landed all the same. With no
    # retry left to look before, the look made before the failure is raised is
    # the one that finds it.
    write = _a_write(*[_github_answered(500)] * (SOME_RETRIES + 1))

    Scenario() \
        .when(lambda: with_retries(write.attempt, retries=SOME_RETRIES,
                                   wait_ms=DONT_CARE_WAIT_MS,
                                   landed=_found_once_made(write, SOME_LANDED_ANSWER,
                                                           times=SOME_RETRIES + 1),
                                   sleep=write.sleep)) \
        .then(
            all_of(
                the_answer_was(SOME_LANDED_ANSWER),
                _made(write, SOME_RETRIES + 1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("made_before_it_is_found", [
    pytest.param(0, id="the-first-look"),
    pytest.param(1, id="a-look-after-a-500")
])
def test_a_place_taken_by_other_work_is_raised_as_the_look_found_it(
        made_before_it_is_found: int) -> None:
    # Not a look that failed: an answer, and the write's own refusal. Passed
    # over, the write would be made into a place it is refused from - or, where
    # GitHub took it, land over somebody's work.
    write = _a_write(_github_answered(500), SOME_ANSWER)

    Scenario() \
        .when(attempting(lambda: with_retries(
            write.attempt, retries=DONT_CARE_RETRIES, wait_ms=DONT_CARE_WAIT_MS,
            landed=_taken_by_other_work_once_made(write, times=made_before_it_is_found),
            sleep=write.sleep
        ))) \
        .then(
            all_of(
                an_error_was_raised(TakenByOtherWork),
                _made(write, made_before_it_is_found)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("failure", "said"), [
    pytest.param(lambda: _github_answered(500), "GitHub answered 500 Internal Server Error",
                 id="an-answer"),
    pytest.param(lambda: httpx2.ConnectError(SOME_TRANSPORT_FAILURE), SOME_TRANSPORT_FAILURE,
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


def _found(landed: str | None) -> Any:
    """A look for the write answering with what landed, or `None` for nothing."""
    def look() -> str | None:
        return landed

    return look


def _a_look_that_fails() -> Any:
    """A look for the write that never reaches GitHub - a request to the same
    GitHub as the write, failing with it."""
    def look() -> str | None:
        raise httpx2.ConnectError(SOME_TRANSPORT_FAILURE)

    return look


def _found_once_made(write: _Write, landed: str, times: int = 1) -> Any:
    """A look for the write finding nothing until the write was made `times`
    times, and then `landed` - one GitHub carried out while answering
    otherwise."""
    def look() -> str | None:
        return landed if write.attempt.call_count >= times else None

    return look


def _taken_by_other_work_once_made(write: _Write, times: int) -> Any:
    """A look for the write finding nothing until the write was made `times`
    times, and then the place it would land taken by other work."""
    def look() -> str | None:
        if write.attempt.call_count >= times:
            raise TakenByOtherWork(DONT_CARE_WHAT_THE_LOOK_SAID)

        return None

    return look


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
