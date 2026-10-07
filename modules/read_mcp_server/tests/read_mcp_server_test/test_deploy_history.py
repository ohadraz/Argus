"""Deploy history, said as `ChangeEvent`s, from the deployment platform's port.

What the platform recorded and how it is asked are the adapter's, and pinned in
its own suite. What is left here is the part that is Argus's: which deployments a
window holds, in what order the history is answered, what a deploy is said as -
and that a platform that did not answer is never "nothing was deployed".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core import parse_iso, to_iso
from argus_core.models import ChangeEvent, ChangeKind
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformReads,
    DeploymentRecord,
    PlatformRefused,
    PlatformUnreachable,
)
from read_mcp_server.change_source import ChangeSourceUnavailable
from read_mcp_server.deploy_history import fetch_deploys, the_revisions_deployed

SOME_APPLICATION = "kukibuki-service"
A_DEPLOY_MINUTE = "2026-08-20T11:05:00Z"
A_WHILE = timedelta(hours=1)


@pytest.mark.unit
def test_a_recorded_deployment_becomes_a_deploy_event() -> None:
    some_revision = "9f4c1e7b2a3d5c8e"

    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of(some_revision, at=A_DEPLOY_MINUTE)
        )) \
        .when(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=a_while_before(A_DEPLOY_MINUTE),
            window_end=a_while_after(A_DEPLOY_MINUTE),
            platform=platform
        )) \
        .then(all_of(
            _the_deploys_are(some_revision),
            _every_deploy_is_of_kind(ChangeKind.DEPLOY),
            _the_first_deploy_took_effect_at(A_DEPLOY_MINUTE)
        ))


@pytest.mark.unit
def test_a_deploy_event_carries_who_deployed_it_and_from_where() -> None:
    some_username = "kuki"
    some_repo_url = "https://github.com/kuki/k8s-configs"

    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of(
                "dont-care-revision",
                at=A_DEPLOY_MINUTE,
                initiated_by=some_username,
                repo_url=some_repo_url
            )
        )) \
        .when(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=a_while_before(A_DEPLOY_MINUTE),
            window_end=a_while_after(A_DEPLOY_MINUTE),
            platform=platform
        )) \
        .then(all_of(
            _the_first_deploy_was_made_by(some_username),
            _the_first_deploy_came_from(some_repo_url)
        ))


@pytest.mark.unit
def test_a_deploy_says_what_it_shipped_and_not_only_that_it_happened() -> None:
    # What this cost, measured on a real walk. Argus names two causes for a
    # deployment that broke a service - the code in it was bad, or a
    # configuration value in it was - and tells the model to prefer the second
    # "whenever the change that landed was to configuration rather than to
    # code". Nothing told it which had landed: the path was already read here
    # and went out as a suffix on the repository URL, while the summary - the
    # field a reader reads - said "deployed revision <sha>", which is true of
    # every deployment there has ever been.
    #
    # The walk ranked both readings, named the moved port in the second, and
    # chose the first. On that evidence either ranking is defensible, which is
    # the definition of evidence that does not decide anything.
    some_path = "deploy/values-production.yaml"

    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of("dont-care-revision", at=A_DEPLOY_MINUTE, path=some_path)
        )) \
        .when(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=a_while_before(A_DEPLOY_MINUTE),
            window_end=a_while_after(A_DEPLOY_MINUTE),
            platform=platform
        )) \
        .then(_the_first_deploy_says_it_shipped(some_path))


@pytest.mark.unit
def test_deploys_outside_the_window_are_discarded() -> None:
    # The platform answers with an application's entire history, so the window
    # is this channel's own job.
    window_start = a_while_before(A_DEPLOY_MINUTE)
    window_end = a_while_after(A_DEPLOY_MINUTE)
    the_revision_deployed_inside_the_window = "inside"

    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of("deployed-before-the-window", at=a_while_before(window_start)),
            a_deployment_of(the_revision_deployed_inside_the_window, at=A_DEPLOY_MINUTE),
            a_deployment_of("deployed-after-the-window", at=a_while_after(window_end))
        )) \
        .when(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=window_start,
            window_end=window_end,
            platform=platform
        )) \
        .then(_the_deploys_are(the_revision_deployed_inside_the_window))


@pytest.mark.unit
def test_an_application_that_never_deployed_yields_no_events() -> None:
    Scenario() \
        .given(platform := _a_platform_that_recorded()) \
        .when(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=a_while_before(A_DEPLOY_MINUTE),
            window_end=a_while_after(A_DEPLOY_MINUTE),
            platform=platform
        )) \
        .then(_no_deploys_were_returned())


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [PlatformUnreachable("platform is down"), PlatformRefused("not this answer")],
    ids=["unreachable", "refused"]
)
def test_a_platform_that_did_not_answer_raises_rather_than_reporting_no_changes(
    failure: DeploymentPlatformError
) -> None:
    # "The deploy API was down" and "nothing changed" are opposite facts.
    # Collapsing them would let an outage become evidence of absence.
    Scenario() \
        .given(platform := _a_platform_failing_with(failure)) \
        .when(attempting(lambda: fetch_deploys(
            SOME_APPLICATION,
            window_start=a_while_before(A_DEPLOY_MINUTE),
            window_end=a_while_after(A_DEPLOY_MINUTE),
            platform=platform
        ))) \
        .then(an_error_was_raised(ChangeSourceUnavailable))


@pytest.mark.unit
def test_every_revision_deployed_comes_back_with_no_window_applied() -> None:
    # What a deployment is compared against is the revision deployed before it,
    # and that revision is under no obligation to fall inside any window an
    # investigation happens to be reading. Windowed, the comparison would silently
    # be against whatever the window's oldest entry happened to be - a diff of the
    # wrong thing, indistinguishable from a diff of the right one.
    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of("long-ago", at=a_while_before(A_DEPLOY_MINUTE)),
            a_deployment_of("just-now", at=A_DEPLOY_MINUTE)
        )) \
        .when(lambda: the_revisions_deployed(SOME_APPLICATION, platform=platform)) \
        .then(_the_deploys_are("long-ago", "just-now"))


@pytest.mark.unit
def test_the_revisions_deployed_are_answered_oldest_first() -> None:
    # The order is the whole of how "the revision deployed before this one" is
    # found. The platform's own ordering is its business and not a promise a
    # diagnosis may rest on, so the history is put in time order here.
    Scenario() \
        .given(platform := _a_platform_that_recorded(
            a_deployment_of("second", at=A_DEPLOY_MINUTE),
            a_deployment_of("first", at=a_while_before(A_DEPLOY_MINUTE))
        )) \
        .when(lambda: the_revisions_deployed(SOME_APPLICATION, platform=platform)) \
        .then(_the_deploys_are("first", "second"))


@pytest.mark.unit
def test_an_application_that_never_deployed_has_no_revisions_to_answer_with() -> None:
    Scenario() \
        .given(platform := _a_platform_that_recorded()) \
        .when(lambda: the_revisions_deployed(SOME_APPLICATION, platform=platform)) \
        .then(_no_deploys_were_returned())


@pytest.mark.unit
def test_the_history_is_asked_of_the_application_named() -> None:
    Scenario() \
        .given(platform := _a_platform_that_recorded()) \
        .when(lambda: the_revisions_deployed(SOME_APPLICATION, platform=platform)) \
        .then(lambda _: _the_history_was_asked_of(platform, SOME_APPLICATION))


def a_while_before(moment: str) -> str:
    return to_iso(parse_iso(moment) - A_WHILE)


def a_while_after(moment: str) -> str:
    return to_iso(parse_iso(moment) + A_WHILE)


def a_deployment_of(revision: str,
                    at: str,
                    initiated_by: str | None = "kuki",
                    repo_url: str | None = "https://github.com/kuki/k8s-configs",
                    path: str | None = "apps/target-service/production"
                    ) -> DeploymentRecord:
    return DeploymentRecord(
        history_id=12,
        revision=revision,
        deployed_at=at,
        repo_url=repo_url,
        path=path,
        initiated_by=initiated_by
    )


def _a_platform_that_recorded(*deployments: DeploymentRecord) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.deployments_of.return_value = list(deployments)
    return platform


def _a_platform_failing_with(failure: DeploymentPlatformError) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.deployments_of.side_effect = failure
    return platform


def _the_history_was_asked_of(platform: Any, application: str) -> bool:
    asked = [call.args for call in platform.deployments_of.call_args_list]

    if asked != [(application,)]:
        raise AssertionError(
            f"Expected the history of [{application}] to be asked for once, and "
            f"the platform was asked {asked}."
        )

    return True


def _the_deploys_are(*expected_revisions: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        actual = [deploy.reference for deploy in deploys]

        if actual != list(expected_revisions):
            raise AssertionError(
                f"Expected deploys of {list(expected_revisions)}, got {actual}."
            )

        return True

    return assertion


def _no_deploys_were_returned() -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        if deploys:
            raise AssertionError(f"Expected no deploys, got {len(deploys)}.")

        return True

    return assertion


def _every_deploy_is_of_kind(expected_kind: ChangeKind) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        kinds = {deploy.kind for deploy in deploys}

        if kinds != {expected_kind}:
            raise AssertionError(f"Expected only [{expected_kind}], got {kinds}.")

        return True

    return assertion


def _the_first_deploy_took_effect_at(expected_moment: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        if deploys[0].occurred_at != expected_moment:
            raise AssertionError(
                f"Expected the deploy at [{expected_moment}], got "
                f"[{deploys[0].occurred_at}]."
            )

        return True

    return assertion


def _the_first_deploy_was_made_by(expected_actor: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        if deploys[0].actor != expected_actor:
            raise AssertionError(
                f"Expected the deploy to be made by [{expected_actor}], got "
                f"[{deploys[0].actor}]."
            )

        return True

    return assertion


def _the_first_deploy_came_from(expected_repo_url: str) -> Assertion[list[ChangeEvent]]:
    def assertion(deploys: list[ChangeEvent]) -> bool:
        source = deploys[0].source

        if source is None or expected_repo_url not in source:
            raise AssertionError(
                f"Expected the deploy to come from [{expected_repo_url}], got "
                f"[{source}]."
            )

        return True

    return assertion


def _the_first_deploy_says_it_shipped(expected_path: str) -> Assertion[list[ChangeEvent]]:
    """That the summary names what the deployment touched, not only that one
    happened.

    Against `summary` rather than `source`, and that is the point of the test:
    the path already reached the model as a suffix on a URL, and the field it
    reads said "deployed revision <sha>" - which is true of every deployment
    there has ever been.
    """
    def assertion(deploys: list[ChangeEvent]) -> bool:
        summary = deploys[0].summary

        if expected_path not in summary:
            raise AssertionError(
                f"Expected the deploy to say it shipped [{expected_path}], got "
                f"[{summary}]."
            )

        return True

    return assertion
