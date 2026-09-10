from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import agent_communicator
import pytest
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.communicating import communicator_node

from ..framework.builders import a_random_id

"""The one page an incident gets, and the last thing Argus says before it.

Every way an incident can end without a fix arrives at this node, which is what
makes "exactly one page" a property of the graph's shape rather than a rule the
node enforces. What the page says is the other half: a walk that changed
production and put it back, and a walk that never touched it, are different
incidents to be woken for.
"""

type NodeResult = dict[str, Any]

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")


@pytest.fixture
def page() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_communicator.page))


@pytest.mark.unit
def test_the_end_of_the_walk_raises_exactly_one_page(page: MagicMock) -> None:
    # One page per incident, however many candidates were tried on the way.
    # A page per refuted attempt would teach its readers to ignore pages, which
    # costs more than the pages themselves are worth.
    incident_id = a_random_id()

    Scenario() \
        .given(a_walk_with_nothing_left := _an_escalated_walk(incident_id)) \
        .when(lambda: communicator_node(a_walk_with_nothing_left,
                                        page=page)) \
        .then(all_of(_exactly_one_page_was_sent(page),
                     _the_page_was_about(incident_id, page)))


@pytest.mark.unit
def test_a_walk_that_never_touched_production_says_so(page: MagicMock) -> None:
    # The reader is being woken to an incident nothing was done about, and that
    # is the first thing they need to know: production is as the alert found it.
    Scenario() \
        .given(a_walk_that_did_nothing := _an_escalated_walk(a_random_id())) \
        .when(lambda: communicator_node(a_walk_that_did_nothing,
                                        page=page)) \
        .then(_the_page_says("There was no actions Argus could take.", page))


@pytest.mark.unit
def test_a_walk_that_tried_things_says_how_many(page: MagicMock) -> None:
    # The other incident to be woken for: production was changed and put back,
    # twice, and the count is what tells the reader which of the two this is.
    two_attempts = [_an_attempt_on("monthly-spend-feature"),
                    _an_attempt_on("legacy-checkout-fallback")]

    Scenario() \
        .given(a_walk_out_of_moves := _an_escalated_walk(a_random_id(), two_attempts)) \
        .when(lambda: communicator_node(a_walk_out_of_moves,
                                        page=page)) \
        .then(_the_page_says("2 explanation(s) were tried and undone", page))


def _an_escalated_walk(incident_id: str,
                       attempts: list[Attempt] | None = None) -> IncidentState:
    """An incident that has run out of moves, which is all this node reads."""
    return IncidentState(
        incident_id=incident_id,
        alert=DONT_CARE_ALERT,
        status=IncidentStatus.ESCALATED,
        attempts=attempts or []
    )


def _exactly_one_page_was_sent(page: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if page.call_count != 1:
            raise AssertionError(
                f"expected exactly one page, got {page.call_count}"
            )

        return True

    return assertion


def _the_page_was_about(incident_id: str, page: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        paged_about = page.call_args.args[0]
        if paged_about != incident_id:
            raise AssertionError(
                f"expected the page to be about [{incident_id}], "
                f"it was about [{paged_about}]"
            )

        return True

    return assertion


def _the_page_says(expected: str, page: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        said = page.call_args.args[1]
        if expected not in said:
            raise AssertionError(
                f"expected the page to say [{expected}], it said [{said}]"
            )

        return True

    return assertion


def _an_attempt_on(subject: str) -> Attempt:
    return Attempt(subject=subject, enabled=False, occurred_at="2026-08-29T16:00:00Z")
