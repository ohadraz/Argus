"""What the platform's failures mean, told apart from what its answers mean.

The one question asked here is the one a walk asks: can anything still be acted
through this? So a refused connection, a request that ran out of time and a
platform reporting its own API unavailable are one answer, because a caller's
next move is the same for all three - and a platform that answered and rejected
what it was asked is the opposite answer, however loudly it rejected it.

Vocabulary rather than policy, which is why nothing here raises. Recognising the
platform's own way of saying it is not serving belongs with the rest of what the
platform says; what to do about it belongs to each action, and each action's own
name for its failure is what that action's callers catch.
"""

from __future__ import annotations

import httpx
import pytest
from argus_testkit import Assertion, Scenario, all_of
from write_mcp_server.argocd import could_not_be_reached

SOME_URL = "http://argocd.invalid/api/v1/applications/io-shop"


@pytest.mark.unit
def test_a_platform_that_refused_the_connection_could_not_be_reached() -> None:
    refused = httpx.ConnectError("connection refused")

    Scenario() \
        .given(refused) \
        .when(lambda: could_not_be_reached(refused)) \
        .then(all_of(_it_is_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_request_that_ran_out_of_time_could_not_be_reached() -> None:
    # The platform Argus would have acted through took longer than an action may
    # take. Nothing was changed, and the read that matters is unchanged too: a
    # caller cannot act through this, whether it is down or merely unresponsive.
    ran_out = httpx.ReadTimeout("timed out")

    Scenario() \
        .given(ran_out) \
        .when(lambda: could_not_be_reached(ran_out)) \
        .then(all_of(_it_is_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_platform_reporting_its_own_api_unavailable_could_not_be_reached() -> None:
    # What a downed Argo CD actually looks like from a client: the API server is
    # not serving and the thing in front of it says so. The platform answered,
    # and what it answered is that it is not answering for itself.
    unavailable = _what_a_platform_answers(503)

    Scenario() \
        .given(unavailable) \
        .when(lambda: could_not_be_reached(unavailable)) \
        .then(all_of(_it_is_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_gateway_with_nothing_behind_it_could_not_be_reached() -> None:
    # The same outage seen one hop further out, and the same answer. Which of
    # the two a caller gets depends on how the platform is fronted, which is not
    # a fact about whether Argus can act.
    nothing_behind_it = _what_a_platform_answers(502)

    Scenario() \
        .given(nothing_behind_it) \
        .when(lambda: could_not_be_reached(nothing_behind_it)) \
        .then(all_of(_it_is_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_an_action_the_platform_rejected_is_not_unreachability() -> None:
    # The distinction the whole change rests on. A platform that answers and
    # refuses has been reached, so the other actions through it are still worth
    # trying and the one that was refused is what somebody should look at.
    rejected = _what_a_platform_answers(400)

    Scenario() \
        .given(rejected) \
        .when(lambda: could_not_be_reached(rejected)) \
        .then(all_of(_it_is_not_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_an_application_the_platform_does_not_have_is_not_unreachability() -> None:
    # A reachable platform saying it has never heard of this application. Read
    # as unreachability it would take four actions away over a name somebody
    # typed wrong.
    never_heard_of_it = _what_a_platform_answers(404)

    Scenario() \
        .given(never_heard_of_it) \
        .when(lambda: could_not_be_reached(never_heard_of_it)) \
        .then(all_of(_it_is_not_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_failure_that_is_not_the_platform_at_all_is_not_unreachability() -> None:
    # The guard against a predicate that answers yes to everything it is shown.
    # A bug in the adapter is not evidence about the platform, and reporting it
    # as an unreachable platform would have a walk pass over four actions
    # because Argus could not read its own response.
    a_bug_of_our_own = ValueError("could not read the resource tree")

    Scenario() \
        .given(a_bug_of_our_own) \
        .when(lambda: could_not_be_reached(a_bug_of_our_own)) \
        .then(all_of(_it_is_not_read_as_an_unreachable_platform()))


def _what_a_platform_answers(status: int) -> httpx.HTTPStatusError:
    """The failure `raise_for_status` raises for one of the platform's answers.

    Built whole rather than stubbed, because what the predicate reads is the
    response hanging off the error, and an error carrying no response would be a
    different case from every one of these.
    """
    request = httpx.Request("POST", SOME_URL)

    return httpx.HTTPStatusError(
        f"answered {status}",
        request=request,
        response=httpx.Response(status, request=request)
    )


def _it_is_read_as_an_unreachable_platform() -> Assertion[bool]:
    def assertion(unreachable: bool) -> bool:
        if not unreachable:
            raise AssertionError(
                "Expected the failure to be read as a platform that could not "
                "be reached, and it was read as one the platform answered."
            )

        return True

    return assertion


def _it_is_not_read_as_an_unreachable_platform() -> Assertion[bool]:
    def assertion(unreachable: bool) -> bool:
        if unreachable:
            raise AssertionError(
                "Expected the failure to be read as one the platform answered, "
                "and it was read as a platform that could not be reached."
            )

        return True

    return assertion
