from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_core.config import Settings
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.timestamps import parse_iso, to_iso
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.argocd import fetch_argocd_application, fetch_deploys
from read_mcp_server.change_source import ChangeSourceUnavailable


@pytest.mark.unit
def test_a_revision_history_entry_becomes_a_deploy_event() -> None:
    some_revision = "9f4c1e7b2a3d5c8e"
    some_deploy_minute = A_DEPLOY_MINUTE
    argocd = a_mock_argocd_server()
    argocd_reported = partial(_returning, argocd)

    Scenario() \
        .given(
            argocd_reported(
                an_application_deployed_at(some_deploy_minute, revision=some_revision)
            )
        ) \
        .when(
            lambda: fetch_deploys(
                SOME_APPLICATION,
                window_start=a_while_before(some_deploy_minute),
                window_end=a_while_after(some_deploy_minute),
                fetch=argocd,
            )
        ) \
        .then(all_of(
            _the_deploys_are(some_revision),
            _every_deploy_is_of_kind(ChangeKind.DEPLOY),
            _the_first_deploy_took_effect_at(some_deploy_minute),
        ))


@pytest.mark.unit
def test_a_deploy_event_carries_who_deployed_it_and_from_where() -> None:
    some_username = "kuki"
    some_repo_url = "https://github.com/kuki/k8s-configs"
    some_deploy_minute = A_DEPLOY_MINUTE
    argocd = a_mock_argocd_server()
    argocd_reported = partial(_returning, argocd)

    Scenario() \
        .given(
            argocd_reported(
                an_application_deployed_at(
                    some_deploy_minute, username=some_username, repo_url=some_repo_url
                )
            )
        ) \
        .when(
            lambda: fetch_deploys(
                SOME_APPLICATION,
                window_start=a_while_before(some_deploy_minute),
                window_end=a_while_after(some_deploy_minute),
                fetch=argocd,
            )
        ) \
        .then(all_of(
            _the_first_deploy_was_made_by(some_username),
            _the_first_deploy_came_from(some_repo_url),
        ))


@pytest.mark.unit
def test_an_entry_without_a_deploy_start_time_still_maps() -> None:
    # Argo CD guarantees `deployedAt` and does not guarantee `deployStartedAt`
    # - it is a pointer in Argo CD's own type, so a real response may omit it.
    some_deploy_minute = A_DEPLOY_MINUTE
    some_revision = "9f4c1e7b2a3d5c8e"
    argocd = a_mock_argocd_server()
    argocd_reported = partial(_returning, argocd)

    Scenario() \
        .given(
            argocd_reported(
                an_application_deployed_at(
                    some_deploy_minute, revision=some_revision, reporting_a_start_time=False
                )
            )
        ) \
        .when(
            lambda: fetch_deploys(
                SOME_APPLICATION,
                window_start=a_while_before(some_deploy_minute),
                window_end=a_while_after(some_deploy_minute),
                fetch=argocd,
            )
        ) \
        .then(
            _the_deploys_are(some_revision)
        )


@pytest.mark.unit
def test_deploys_outside_the_window_are_discarded() -> None:
    # Argo CD's API takes no time parameters and answers with an application's
    # entire history, so the window is the adapter's own job.
    some_deploy_minute = A_DEPLOY_MINUTE
    window_start = a_while_before(some_deploy_minute)
    window_end = a_while_after(some_deploy_minute)
    the_revision_deployed_inside_the_window = "inside"
    argocd = a_mock_argocd_server()
    argocd_reported = partial(_returning, argocd)

    Scenario() \
        .given(
            argocd_reported(
                an_application_with(
                    a_deploy_of("deployed-before-the-window", at=a_while_before(window_start)),
                    a_deploy_of(the_revision_deployed_inside_the_window, at=some_deploy_minute),
                    a_deploy_of("deployed-after-the-window", at=a_while_after(window_end)),
                )
            )
        ) \
        .when(
            lambda: fetch_deploys(
                SOME_APPLICATION,
                window_start=window_start,
                window_end=window_end,
                fetch=argocd,
            )
        ) \
        .then(
            _the_deploys_are(the_revision_deployed_inside_the_window)
        )


@pytest.mark.unit
def test_an_application_that_never_deployed_yields_no_events() -> None:
    # Argo CD omits `history` entirely when there is none - it is `omitempty`
    # in Argo CD's own type - so an absent key is a real response, not a
    # broken one.
    some_deploy_minute = A_DEPLOY_MINUTE
    argocd = a_mock_argocd_server()
    argocd_reported = partial(_returning, argocd)

    Scenario() \
        .given(
            argocd_reported(an_application_that_never_deployed())
        ) \
        .when(
            lambda: fetch_deploys(
                SOME_APPLICATION,
                window_start=a_while_before(some_deploy_minute),
                window_end=a_while_after(some_deploy_minute),
                fetch=argocd,
            )
        ) \
        .then(
            _no_deploys_were_returned()
        )


@pytest.mark.unit
def test_a_configured_token_is_sent_as_a_bearer_credential() -> None:
    some_token = "some-argocd-token"
    get = a_mock_http_get()
    the_server_answered_with = partial(_returning, get)
    the_request_carried = partial(_the_request_carried, get)

    Scenario() \
        .given(
            the_server_answered_with(an_ok_response())
        ) \
        .when(
            lambda: fetch_argocd_application(
                SOME_APPLICATION,
                settings=Settings(argocd_auth_token=some_token),
                get=get,
            )
        ) \
        .then(
            the_request_carried(authorization=f"Bearer {some_token}")
        )


@pytest.mark.unit
def test_no_configured_token_means_no_authorization_header() -> None:
    # An empty setting means the stand-in, which needs no credential. Sending
    # a placeholder would be inventing one.
    no_token = ""
    get = a_mock_http_get()
    the_server_answered_with = partial(_returning, get)
    the_request_carried = partial(_the_request_carried, get)

    Scenario() \
        .given(
            the_server_answered_with(an_ok_response())
        ) \
        .when(
            lambda: fetch_argocd_application(
                SOME_APPLICATION,
                settings=Settings(argocd_auth_token=no_token),
                get=get,
            )
        ) \
        .then(
            the_request_carried(authorization=None)
        )


@pytest.mark.unit
def test_the_request_goes_to_the_configured_application_path() -> None:
    some_base_url = "http://kuki-argocd:9000"
    a_real_argocd_path = "/api/v1/applications/{application}"
    get = a_mock_http_get()
    the_server_answered_with = partial(_returning, get)
    the_requested_url_was = partial(_the_requested_url_was, get)

    Scenario() \
        .given(
            the_server_answered_with(an_ok_response())
        ) \
        .when(
            lambda: fetch_argocd_application(
                SOME_APPLICATION,
                settings=Settings(
                    argocd_base_url=some_base_url, argocd_application_path=a_real_argocd_path
                ),
                get=get,
            )
        ) \
        .then(
            the_requested_url_was(f"{some_base_url}/api/v1/applications/{SOME_APPLICATION}")
        )


@pytest.mark.unit
def test_a_path_without_a_placeholder_is_used_as_written() -> None:
    some_base_url = "http://kuki-argocd:9000"
    a_path_naming_no_application = "/argocd"
    get = a_mock_http_get()
    the_server_answered_with = partial(_returning, get)
    the_requested_url_was = partial(_the_requested_url_was, get)

    Scenario() \
        .given(
            the_server_answered_with(an_ok_response())
        ) \
        .when(
            lambda: fetch_argocd_application(
                SOME_APPLICATION,
                settings=Settings(
                    argocd_base_url=some_base_url,
                    argocd_application_path=a_path_naming_no_application,
                ),
                get=get,
            )
        ) \
        .then(
            the_requested_url_was(f"{some_base_url}{a_path_naming_no_application}")
        )


@pytest.mark.unit
def test_an_error_response_raises_rather_than_reporting_no_changes() -> None:
    # "The deploy API was down" and "nothing changed" are opposite facts.
    # Collapsing them would let an outage become evidence of absence.
    get = a_mock_http_get()
    the_server_answered_with = partial(_returning, get)

    Scenario() \
        .given(
            the_server_answered_with(an_error_response())
        ) \
        .when(
            attempting(
                lambda: fetch_argocd_application(
                    SOME_APPLICATION, settings=Settings(), get=get
                )
            )
        ) \
        .then(
            an_error_was_raised(ChangeSourceUnavailable)
        )


@pytest.mark.unit
def test_an_unreachable_server_raises_rather_than_reporting_no_changes() -> None:
    get = a_mock_http_get()
    the_server_was_unreachable = partial(_raising, get)

    Scenario() \
        .given(
            the_server_was_unreachable(httpx.ConnectError("no route to host"))
        ) \
        .when(
            attempting(
                lambda: fetch_argocd_application(
                    SOME_APPLICATION, settings=Settings(), get=get
                )
            )
        ) \
        .then(
            an_error_was_raised(ChangeSourceUnavailable)
        )


SOME_APPLICATION = "kukibuki-service"
A_DEPLOY_MINUTE = "2026-08-20T11:05:00Z"
A_WHILE = timedelta(hours=1)


def a_while_before(moment: str) -> str:
    return to_iso(parse_iso(moment) - A_WHILE)


def a_while_after(moment: str) -> str:
    return to_iso(parse_iso(moment) + A_WHILE)


def a_mock_argocd_server() -> Any:
    return create_autospec(fetch_argocd_application)


def a_mock_http_get() -> Any:
    return create_autospec(httpx.get)


def a_deploy_of(
    revision: str,
    at: str,
    username: str = "kuki",
    repo_url: str = "https://github.com/kuki/k8s-configs",
    reporting_a_start_time: bool = True,
) -> dict[str, Any]:
    """One `status.history` entry, in Argo CD's own wire shape."""
    entry: dict[str, Any] = {
        "id": 12,
        "revision": revision,
        "deployedAt": at,
        "source": {
            "repoURL": repo_url,
            "path": "apps/target-service/production",
            "targetRevision": "main",
        },
        "initiatedBy": {"username": username},
    }

    if reporting_a_start_time:
        entry["deployStartedAt"] = to_iso(parse_iso(at) - timedelta(minutes=1))

    return entry


def an_application_with(*history: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": {"name": SOME_APPLICATION, "namespace": "argocd"},
        "status": {"history": list(history)},
    }


def an_application_deployed_at(
    moment: str,
    revision: str = "9f4c1e7b2a3d5c8e",
    username: str = "kuki",
    repo_url: str = "https://github.com/kuki/k8s-configs",
    reporting_a_start_time: bool = True,
) -> dict[str, Any]:
    return an_application_with(
        a_deploy_of(
            revision,
            at=moment,
            username=username,
            repo_url=repo_url,
            reporting_a_start_time=reporting_a_start_time,
        )
    )


def an_application_that_never_deployed() -> dict[str, Any]:
    # No `history` key at all, which is what Argo CD actually sends.
    return {
        "metadata": {"name": SOME_APPLICATION, "namespace": "argocd"},
        "status": {},
    }


def _returning(double: Any, value: Any) -> Callable[[], None]:
    def step() -> None:
        double.return_value = value

    return step


def _raising(double: Any, error: Exception) -> Callable[[], None]:
    def step() -> None:
        double.side_effect = error

    return step


def _the_deploys_are(*expected_revisions: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        actual = [deploy.reference for deploy in deploys]
        assert actual == list(expected_revisions), (
            f"Expected deploys of {list(expected_revisions)}, got {actual}."
        )
        return True

    return assertion


def _no_deploys_were_returned() -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        assert deploys == [], f"Expected no deploys, got {len(deploys)}."
        return True

    return assertion


def _every_deploy_is_of_kind(expected_kind: ChangeKind) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        kinds = {deploy.kind for deploy in deploys}
        assert kinds == {expected_kind}, f"Expected only [{expected_kind}], got {kinds}."
        return True

    return assertion


def _the_first_deploy_took_effect_at(expected_moment: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        assert deploys[0].occurred_at == expected_moment, (
            f"Expected the deploy at [{expected_moment}], got [{deploys[0].occurred_at}]."
        )
        return True

    return assertion


def _the_first_deploy_was_made_by(expected_actor: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        assert deploys[0].actor == expected_actor, (
            f"Expected the deploy to be made by [{expected_actor}], got [{deploys[0].actor}]."
        )
        return True

    return assertion


def _the_first_deploy_came_from(expected_repo_url: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        source = deploys[0].source
        assert source is not None and expected_repo_url in source, (
            f"Expected the deploy to come from [{expected_repo_url}], got [{source}]."
        )
        return True

    return assertion


def _the_request_carried(get: Any, authorization: str | None) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        headers = get.call_args.kwargs["headers"]
        actual = headers.get("Authorization")
        assert actual == authorization, (
            f"Expected the request to carry authorization [{authorization}], got [{actual}]."
        )
        return True

    return assertion


def _the_requested_url_was(get: Any, expected_url: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        actual = get.call_args.args[0]
        assert actual == expected_url, f"Expected a request to [{expected_url}], got [{actual}]."
        return True

    return assertion

def an_ok_response() -> httpx.Response:
    return _a_response(200, json=an_application_that_never_deployed())


def an_error_response() -> httpx.Response:
    return _a_response(500, text="argocd is unwell")


def _a_response(status_code: int, **body: Any) -> httpx.Response:
    # A response needs the request that produced it, or `raise_for_status()`
    # refuses to say anything about it - and a `RuntimeError` from httpx would
    # be indistinguishable, to the test, from the adapter handling a real HTTP
    # error correctly.
    return httpx.Response(
        status_code, request=httpx.Request("GET", "http://kuki-argocd:9000"), **body
    )
