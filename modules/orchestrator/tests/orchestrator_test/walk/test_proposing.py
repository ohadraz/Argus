from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation.tools import fetch_recent_flag_changes
from argus_core.events import FlagChangesRetrieved, IncidentEvent
from argus_core.models.alert import Alert
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling
from orchestrator.walk.proposing import mitigation_proposal_node

from ..framework.builders import a_determined_hypothesis, an_incident_state

"""Choosing the reversible action that answers the hypothesis, and only that.

The node reads the flag provider and hands the choice to the agent; nothing
mutating happens here, which is what leaves room for the gate between this node
and the one that acts.

A provider that cannot be read is not an error to raise. "Nothing changed" and
"I could not find out" both mean there is no action to take, and the incident
goes to a human either way - crashing the graph instead would drop everything
already learned about it.
"""

type NodeResult = dict[str, Any]

DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"


@pytest.fixture
def fetch_flag_changes() -> MagicMock:
    return cast(MagicMock, create_autospec(fetch_recent_flag_changes))


@pytest.mark.unit
def test_the_proposal_node_proposes_an_action_for_the_flag_that_changed(
    fetch_flag_changes: MagicMock
) -> None:
    the_flag_that_changed = "monthly-spend-feature"

    Scenario() \
        .given(
            calling(lambda: _the_provider_reports(
                fetch_flag_changes, _an_enabling_of(the_flag_that_changed))),
            a_mitigating_incident := _a_mitigating_incident()
        ) \
        .when(lambda: mitigation_proposal_node(
            a_mitigating_incident, fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(_the_proposed_action_is_about(the_flag_that_changed),
                     _the_proposed_action_turns_the_flag_off()))


@pytest.mark.unit
def test_the_proposal_node_proposes_nothing_when_the_provider_cannot_be_read(
    fetch_flag_changes: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            a_mitigating_incident := _a_mitigating_incident()
        ) \
        .when(lambda: mitigation_proposal_node(
            a_mitigating_incident, fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(_nothing_was_proposed())


@pytest.mark.unit
def test_the_graph_says_what_flag_history_it_chose_the_action_from(
    fetch_flag_changes: MagicMock
) -> None:
    # The action rests on this and nothing else: which flag moved, which way,
    # and when. Unpublished, the page shows Argus reverting a flag with no
    # account of how it came to be that flag - the one step of the walk an
    # audience most wants to check.
    published: list[IncidentEvent] = []
    what_the_flag_provider_recorded = [_an_enabling_of("monthly-spend-feature")]

    Scenario() \
        .given(
            calling(lambda: _the_provider_reports(
                fetch_flag_changes, *what_the_flag_provider_recorded)),
            a_mitigating_incident := _a_mitigating_incident()
        ) \
        .when(lambda: mitigation_proposal_node(a_mitigating_incident,
                                               fetch_flag_changes=fetch_flag_changes,
                                               publisher=published.append)) \
        .then(_the_history_published_is(what_the_flag_provider_recorded, published))


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_not_published_as_an_empty_one(
    fetch_flag_changes: MagicMock
) -> None:
    # "Nothing changed" and "the provider did not answer" lead to the same
    # place - no action - and are not the same fact. A page showing an empty
    # history for the second would be stating that nothing had changed.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            a_mitigating_incident := _a_mitigating_incident()
        ) \
        .when(lambda: mitigation_proposal_node(a_mitigating_incident,
                                               fetch_flag_changes=fetch_flag_changes,
                                               publisher=published.append)) \
        .then(_no_history_was_published(published))


def _the_provider_reports(fetch_flag_changes: MagicMock,
                          *changes: FlagChange) -> None:
    fetch_flag_changes.return_value = list(changes)


def _the_provider_cannot_be_reached(fetch_flag_changes: MagicMock) -> None:
    fetch_flag_changes.side_effect = RuntimeError("The Feature Flag provider could not be reached.")


def _a_mitigating_incident() -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={"hypothesis": a_determined_hypothesis(state.incident_id)}
    )


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)


def _the_proposed_action_is_about(flag: str) -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        proposed = updates["proposed_action"]
        if proposed is None:
            raise AssertionError(
                f"Expected an action about [{flag}], nothing was proposed."
            )

        if proposed.flag != flag:
            raise AssertionError(
                f"Expected an action about [{flag}], it was about [{proposed.flag}]."
            )

        return True

    return assertion


def _the_proposed_action_turns_the_flag_off() -> Assertion[NodeResult]:
    """The flag was switched on and that is what is being undone, so the action
    is the opposite of the change it answers - never a repeat of it."""
    def assertion(updates: NodeResult) -> bool:
        proposed = updates["proposed_action"]
        if proposed is None or proposed.enabled is not False:
            raise AssertionError(
                f"Expected the action to turn the flag off, it was {proposed!r}."
            )

        return True

    return assertion


def _nothing_was_proposed() -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        proposed = updates["proposed_action"]
        if proposed is not None:
            raise AssertionError(
                f"Expected no action to be proposed, got {proposed!r}."
            )

        return True

    return assertion


def _the_history_published_is(expected: list[FlagChange],
                              published: list[IncidentEvent]
                              ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        read = [event for event in published
                if isinstance(event, FlagChangesRetrieved)]
        if len(read) != 1:
            raise AssertionError(
                f"expected one FlagChangesRetrieved, got {len(read)}"
            )

        if read[0].changes != expected:
            raise AssertionError(
                f"expected the history {expected} to be published, got "
                f"{read[0].changes}"
            )

        return True

    return assertion


def _no_history_was_published(published: list[IncidentEvent]
                              ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        read = [event for event in published
                if isinstance(event, FlagChangesRetrieved)]
        if read:
            raise AssertionError(
                f"expected an unreadable provider to publish no history, it "
                f"published {read}"
            )

        return True

    return assertion
