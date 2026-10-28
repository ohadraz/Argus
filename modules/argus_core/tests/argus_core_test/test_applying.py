"""Whether a request that failed is known not to have been applied.

The line between what a write tier can say it left behind and what it cannot.
A request that never left the process, or one the server answered by saying it
did not handle it, changed nothing; one whose answer was lost, or that the server
faulted part way through, may have changed something nobody can see. One rule for
every write tier that asks over HTTP, because two lists of errors and statuses are
two lists to keep in step.
"""

from __future__ import annotations

import httpx2
import pytest
from argus_core.applying import known_not_applied
from argus_testkit import Scenario, the_answer_was

DONT_CARE_URL = "http://platform.invalid/some/route"


def _answered(method: str, status: int) -> httpx2.HTTPStatusError:
    request = httpx2.Request(method, DONT_CARE_URL)

    return httpx2.HTTPStatusError(
        f"answered {status}",
        request=request,
        response=httpx2.Response(status, request=request)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        httpx2.ConnectError("connection refused"),
        httpx2.ConnectTimeout("timed out connecting"),
        httpx2.PoolTimeout("no connection free")
    ],
    ids=["refused", "connect timed out", "pool timed out"]
)
def test_a_change_that_never_left_the_process_is_known_not_applied(
    failure: Exception
) -> None:
    # No connection was had, so nothing was sent and nothing was done.
    Scenario() \
        .when(lambda: known_not_applied("POST", failure)) \
        .then(the_answer_was(True))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        httpx2.ReadTimeout("timed out"),
        httpx2.WriteTimeout("timed out sending"),
        httpx2.RemoteProtocolError("server disconnected")
    ],
    ids=["read timed out", "write timed out", "disconnected"]
)
def test_a_change_whose_answer_was_lost_may_have_been_applied(failure: Exception) -> None:
    # The request went out, or part of it did, and no answer came back to say
    # what became of it.
    Scenario() \
        .when(lambda: known_not_applied("POST", failure)) \
        .then(the_answer_was(False))


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 503])
def test_a_change_the_server_answered_it_did_not_handle_is_known_not_applied(
    status: int
) -> None:
    # A 4xx is a request read and rejected. A 503 is the server saying it could
    # not handle the request at all (RFC 9110, 15.6.4).
    Scenario() \
        .when(lambda: known_not_applied("POST", _answered("POST", status))) \
        .then(the_answer_was(True))


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 504])
def test_a_change_the_server_failed_part_way_may_have_been_applied(status: int) -> None:
    # A server that faulted while handling the request, or a gateway that lost
    # the answer from behind it: neither says the change was not made.
    Scenario() \
        .when(lambda: known_not_applied("POST", _answered("POST", status))) \
        .then(the_answer_was(False))


@pytest.mark.unit
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "failure",
    [httpx2.ReadTimeout("timed out"), _answered("GET", 500)],
    ids=["timed out", "faulted"]
)
def test_a_read_that_failed_applied_nothing(method: str, failure: Exception) -> None:
    # A read changes nothing, however its answer went missing.
    Scenario() \
        .when(lambda: known_not_applied(method, failure)) \
        .then(the_answer_was(True))


@pytest.mark.unit
def test_a_failure_that_is_not_the_transports_may_have_been_applied() -> None:
    # Anything else - a bug between the request and here - says nothing about
    # what the server did, so it is not taken to say the change was not made.
    Scenario() \
        .when(lambda: known_not_applied("POST", ValueError("some bug"))) \
        .then(the_answer_was(False))
