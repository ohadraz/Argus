"""What the platform's failures mean, and how its sync policy is spoken.

The first question asked here is the one a walk asks: can anything still be
acted through this? So a refused connection, a request that ran out of time and a
platform reporting its own API unavailable are one answer, because a caller's
next move is the same for all three - and a platform that answered and rejected
what it was asked is the opposite answer, however loudly it rejected it.

The second is how the three actions that change live state under Argo CD switch
its automated sync off and back on. The switch is `automated.enabled` and nothing
else: the spec route takes its body as the whole spec, and an `automated` object
written by Argus would replace the one the operator declared.

Vocabulary rather than policy, which is why nothing here raises. Recognising the
platform's own way of saying it is not serving belongs with the rest of what the
platform says; what to do about it belongs to each action, and each action's own
name for its failure is what that action's callers catch.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from argus_testkit import Assertion, Scenario, all_of
from write_mcp_server.argocd import (
    APPLICATION_MERGE_PATCH,
    AUTOMATED,
    ENABLED,
    PATCH_REQUEST_NAME,
    PATCH_REQUEST_PATCH,
    PATCH_REQUEST_TYPE,
    SPEC,
    SYNC_POLICY,
    a_sync_patch,
    could_not_be_reached,
    is_reconciling_itself,
)

SOME_URL = "http://argocd.invalid/api/v1/applications/io-shop"
SOME_APPLICATION = "io-shop"


@pytest.mark.unit
def test_a_platform_that_refused_the_connection_could_not_be_reached() -> None:
    refused = httpx2.ConnectError("connection refused")

    Scenario() \
        .given(refused) \
        .when(lambda: could_not_be_reached(refused)) \
        .then(all_of(_it_is_read_as_an_unreachable_platform()))


@pytest.mark.unit
def test_a_request_that_ran_out_of_time_could_not_be_reached() -> None:
    # The platform Argus would have acted through took longer than an action may
    # take. Nothing was changed, and the read that matters is unchanged too: a
    # caller cannot act through this, whether it is down or merely unresponsive.
    ran_out = httpx2.ReadTimeout("timed out")

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


@pytest.mark.unit
def test_suspending_is_a_merge_patch_switching_automated_sync_off() -> None:
    # The switch and nothing beside it. `prune`, `selfHeal` and the rest stay as
    # the operator declared them, because the patch never names them.
    Scenario() \
        .given(SOME_APPLICATION) \
        .when(lambda: a_sync_patch(SOME_APPLICATION, reconciling=False)) \
        .then(all_of(
            _it_is_a_merge_patch_of(SOME_APPLICATION),
            _it_patches(_the_switch_set_to(False))
        ))


@pytest.mark.unit
def test_restoring_is_a_merge_patch_removing_the_switch() -> None:
    # A merge patch's `null` removes the key, and the platform reads an absent
    # `enabled` as on. Writing `automated` back instead would replace the one
    # the operator declared with Argus's own.
    Scenario() \
        .given(SOME_APPLICATION) \
        .when(lambda: a_sync_patch(SOME_APPLICATION, reconciling=True)) \
        .then(all_of(
            _it_is_a_merge_patch_of(SOME_APPLICATION),
            _it_patches(_the_switch_set_to(None))
        ))


@pytest.mark.unit
def test_an_automated_policy_with_no_switch_is_reconciling_itself() -> None:
    # An `automated` of `{}` means automated. Read as false, an action would be
    # refused by a server this had just called compliant.
    some_application = _an_application_whose_policy_is({AUTOMATED: {}})

    Scenario() \
        .given(some_application) \
        .when(lambda: is_reconciling_itself(some_application)) \
        .then(_it_is_read_as_reconciling(True))


@pytest.mark.unit
def test_an_automated_policy_switched_on_is_reconciling_itself() -> None:
    some_application = _an_application_whose_policy_is(
        {AUTOMATED: {"selfHeal": True, ENABLED: True}}
    )

    Scenario() \
        .given(some_application) \
        .when(lambda: is_reconciling_itself(some_application)) \
        .then(_it_is_read_as_reconciling(True))


@pytest.mark.unit
def test_an_automated_policy_switched_off_is_not_reconciling_itself() -> None:
    # Configured and not syncing, as the platform reads it. An action taken
    # against it has nothing to suspend and nothing to turn back on.
    some_application = _an_application_whose_policy_is(
        {AUTOMATED: {"selfHeal": True, ENABLED: False}}
    )

    Scenario() \
        .given(some_application) \
        .when(lambda: is_reconciling_itself(some_application)) \
        .then(_it_is_read_as_reconciling(False))


@pytest.mark.unit
def test_a_policy_with_no_automated_object_is_not_reconciling_itself() -> None:
    some_application = _an_application_whose_policy_is({})

    Scenario() \
        .given(some_application) \
        .when(lambda: is_reconciling_itself(some_application)) \
        .then(_it_is_read_as_reconciling(False))


def _what_a_platform_answers(status: int) -> httpx2.HTTPStatusError:
    """The failure `raise_for_status` raises for one of the platform's answers.

    Built whole rather than stubbed, because what the predicate reads is the
    response hanging off the error, and an error carrying no response would be a
    different case from every one of these.
    """
    request = httpx2.Request("POST", SOME_URL)

    return httpx2.HTTPStatusError(
        f"answered {status}",
        request=request,
        response=httpx2.Response(status, request=request)
    )


def _an_application_whose_policy_is(policy: dict[str, Any]) -> dict[str, Any]:
    return {SPEC: {SYNC_POLICY: policy}}


def _the_switch_set_to(enabled: bool | None) -> dict[str, Any]:
    return {SPEC: {SYNC_POLICY: {AUTOMATED: {ENABLED: enabled}}}}


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


def _it_is_a_merge_patch_of(application: str) -> Assertion[dict[str, Any]]:
    """The request Argo CD's `PATCH /api/v1/applications/{name}` takes.

    The patch itself a JSON-encoded string, as the vendor's
    `ApplicationPatchRequest` carries it, and its type the merge patch's -
    sent as any other type it is applied differently or not at all.
    """
    def assertion(body: dict[str, Any]) -> bool:
        if body.get(PATCH_REQUEST_NAME) != application:
            raise AssertionError(
                f"Expected the patch to name [{application}], and it named "
                f"[{body.get(PATCH_REQUEST_NAME)}]."
            )

        if body.get(PATCH_REQUEST_TYPE) != APPLICATION_MERGE_PATCH:
            raise AssertionError(
                f"Expected a [{APPLICATION_MERGE_PATCH}] patch, and it was "
                f"[{body.get(PATCH_REQUEST_TYPE)}]."
            )

        if not isinstance(body.get(PATCH_REQUEST_PATCH), str):
            raise AssertionError(
                f"Expected the patch to be carried as a JSON-encoded string, and "
                f"it was [{type(body.get(PATCH_REQUEST_PATCH))}]."
            )

        return True

    return assertion


def _it_patches(expected: dict[str, Any]) -> Assertion[dict[str, Any]]:
    def assertion(body: dict[str, Any]) -> bool:
        patched = json.loads(body[PATCH_REQUEST_PATCH])

        if patched != expected:
            raise AssertionError(
                f"Expected the patch to be {expected}, and it was {patched}."
            )

        return True

    return assertion


def _it_is_read_as_reconciling(reconciling: bool) -> Assertion[bool]:
    def assertion(read: bool) -> bool:
        if read is not reconciling:
            raise AssertionError(
                f"Expected the application to be read as "
                f"{'reconciling itself' if reconciling else 'not reconciling'}, "
                f"and it was read as the opposite."
            )

        return True

    return assertion
