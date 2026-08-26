from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.timestamps import parse_iso, to_iso
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.argocd import fetch_deploys
from read_mcp_server.change_source import ChangeSourceUnavailable
from read_mcp_server.retrieval import get_change_events


@pytest.mark.unit
def test_the_changes_the_source_reports_are_returned() -> None:
    some_revision = "kuki"
    some_change_minute = A_CHANGE_MINUTE
    change_source = a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)

    Scenario() \
        .given(
            the_change_source_reported([a_deploy_of(some_revision, at=some_change_minute)])
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=a_while_before(some_change_minute),
                window_end=a_while_after(some_change_minute),
                source=change_source
            )
        ) \
        .then(all_of(
            _the_changes_are(some_revision),
            _every_change_is_of_kind(ChangeKind.DEPLOY),
        ))


@pytest.mark.unit
def test_a_window_containing_no_change_is_not_an_error() -> None:
    # Nothing changed is a real answer, and the one the Investigator most needs
    # to be able to trust - it is what makes "no change explains this" sayable.
    some_change_minute = A_CHANGE_MINUTE
    change_source = a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)

    Scenario() \
        .given(
            the_change_source_reported([])
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=a_while_before(some_change_minute),
                window_end=a_while_after(some_change_minute),
                source=change_source,
            )
        ) \
        .then(
            _no_changes_were_returned()
        )


@pytest.mark.unit
def test_the_service_and_window_asked_about_are_the_ones_passed_on() -> None:
    # The tool is a delegation, and the thing worth pinning is that it does not
    # quietly widen, narrow or re-anchor what its caller asked for.
    some_change_minute = A_CHANGE_MINUTE
    some_window_start = a_while_before(some_change_minute)
    some_window_end = a_while_after(some_change_minute)
    change_source = a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)
    the_source_was_asked_about = partial(_the_source_was_asked_about, change_source)

    Scenario() \
        .given(
            the_change_source_reported([])
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=some_window_start,
                window_end=some_window_end,
                source=change_source
            )
        ) \
        .then(
            the_source_was_asked_about(
                SOME_SERVICE, window_start=some_window_start, window_end=some_window_end
            )
        )


@pytest.mark.unit
def test_an_unreachable_source_surfaces_as_a_failure() -> None:
    # The tool must not turn "could not ask" into "nothing changed" on its way
    # back up - that is the whole reason the source raises rather than
    # returning an empty list.
    some_change_minute = A_CHANGE_MINUTE
    change_source = a_mock_change_source()
    the_change_source_was_unreachable = partial(_raising, change_source)

    Scenario() \
        .given(
            the_change_source_was_unreachable(
                ChangeSourceUnavailable("could not read deploy history")
            )
        ) \
        .when(
            attempting(
                lambda: get_change_events(
                    SOME_SERVICE,
                    window_start=a_while_before(some_change_minute),
                    window_end=a_while_after(some_change_minute),
                    source=change_source
                )
            )
        ) \
        .then(
            an_error_was_raised(ChangeSourceUnavailable)
        )


SOME_SERVICE = "kukibuki-service"
A_CHANGE_MINUTE = "2026-08-20T11:05:00Z"
A_WHILE = timedelta(hours=1)


def a_while_before(moment: str) -> str:
    return to_iso(parse_iso(moment) - A_WHILE)


def a_while_after(moment: str) -> str:
    return to_iso(parse_iso(moment) + A_WHILE)


def a_mock_change_source() -> Any:
    return create_autospec(fetch_deploys)


def a_deploy_of(revision: str, at: str) -> ChangeEvent:
    some_summary = f"deployed revision {revision}"
    some_actor = "kukibuki"
    some_source = "https://github.com/kukibuki/k8s-configs/apps/target-service/production"

    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=at,
        reference=revision,
        summary=some_summary,
        actor=some_actor,
        source=some_source
    )


def _returning(double: Any, value: Any) -> Callable[[], None]:
    def step() -> None:
        double.return_value = value

    return step


def _raising(double: Any, error: Exception) -> Callable[[], None]:
    def step() -> None:
        double.side_effect = error

    return step


def _the_changes_are(*expected_references: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        actual = [change.reference for change in changes]
        assert actual == list(expected_references), (
            f"Expected changes {list(expected_references)}, got [{actual}]."
        )
        return True

    return assertion


def _no_changes_were_returned() -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        assert changes == [], f"Expected no changes, got [{len(changes)}]."
        return True

    return assertion


def _every_change_is_of_kind(expected_kind: ChangeKind) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        actual_kinds = {change.kind for change in changes}
        assert actual_kinds == {expected_kind}, (
            f"Expected only [{expected_kind}], got [{actual_kinds}]."
        )

        return True

    return assertion


def _the_source_was_asked_about(change_source: Any, 
                                service: str, 
                                window_start: str, 
                                window_end: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        asked_service = change_source.call_args.args[0]
        asked_window = change_source.call_args.kwargs
        actual_window_start = asked_window["window_start"]
        actual_window_end = asked_window["window_end"]

        assert asked_service == service, (
            f"Expected the source to be asked about [{service}], got [{asked_service}]."
        )
        assert actual_window_start == window_start, (
            f"Expected the window to start at [{window_start}], got [{actual_window_start}]."
        )
        assert actual_window_end == window_end, (
            f"Expected the window to end at [{window_end}], got [{actual_window_end}]."
        )

        return True

    return assertion
