"""Filing what an incident tried, and what happens when the filing fails.

Two collaborators, both injected - one that reads back what was done and one
that keeps the record - because what this node does is exactly to join them.
What a record says belongs to `incident_memory` and where it goes belongs to a
deployment; a test of this node that needed either would be testing something
else.

The failure case is the one that matters most here. Nothing downstream reads
what this node produces and this incident is over either way, so a store that is
down has to cost the walk nothing at all - and has to say so, because silence
here is indistinguishable from an incident that had nothing worth filing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.events import IncidentEvent
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Alert,
    IncidentStatus,
    TakenAction,
    Verdict,
)
from argus_testkit import Assertion, Kept, Scenario, all_of
from incident_memory.records import RememberedIncident
from orchestrator.walk.ports import ActionsTaken, RememberIncident
from orchestrator.walk.remembering import remembering_node
from orchestrator.walk.state import IncidentState

DONT_CARE_INCIDENT_ID = "e6e6e6e6-0000-4000-8000-000000000007"
DONT_CARE_HYPOTHESIS_ID = "e6e6e6e6-0000-4000-8000-000000000008"


@pytest.mark.unit
def test_what_was_tried_is_filed_against_the_incident() -> None:
    # The whole point of the node: a later incident asks what was changed here
    # and what each change turned out to be worth, and this is where that
    # answer is written down.
    the_flag_that_did_not_help = "new-checkout-flow"
    filed: Kept[RememberedIncident] = Kept()

    Scenario() \
        .given(
            an_incident_that_is_over := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_is_over,
                actions_taken=_actions(
                    _an_action(the_flag_that_did_not_help, Verdict.REFUTED)
                ),
                remember=_a_store_keeping(filed))
        ) \
        .then(
            all_of(
                _filed_one_record_for(filed, DONT_CARE_INCIDENT_ID),
                _filed_a_record_naming(filed, the_flag_that_did_not_help)
            )
        )


@pytest.mark.unit
def test_an_incident_with_nothing_judged_files_nothing() -> None:
    # Withdrawn mid-measurement, or escalated before anything could be done.
    # A record here would be findable by a later search with nothing to tell it
    # when found.
    filed: Kept[RememberedIncident] = Kept()

    Scenario() \
        .given(
            an_incident_that_measured_nothing := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_measured_nothing,
                actions_taken=_actions(
                    _an_action("new-checkout-flow", Verdict.WITHDRAWN)
                ),
                remember=_a_store_keeping(filed))
        ) \
        .then(_nothing_was_filed(filed))


@pytest.mark.unit
def test_an_incident_with_no_actions_at_all_files_nothing() -> None:
    # The escalation that never got as far as changing anything. There is
    # nothing here a later incident could use, and a record of the description
    # alone would rank against real ones while saying nothing.
    filed: Kept[RememberedIncident] = Kept()

    Scenario() \
        .given(
            an_incident_that_did_nothing := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_did_nothing,
                actions_taken=_actions(),
                remember=_a_store_keeping(filed))
        ) \
        .then(_nothing_was_filed(filed))


@pytest.mark.unit
def test_a_memory_store_that_is_down_does_not_stop_the_walk() -> None:
    # The incident is over and nothing downstream reads this. A node that let a
    # vector store's outage propagate would make an unreachable cache of old
    # incidents into the reason this one ends without its write-up.
    Scenario() \
        .given(
            an_incident_that_is_over := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_is_over,
                actions_taken=_actions(
                    _an_action("new-checkout-flow", Verdict.REFUTED)
                ),
                remember=_a_store_that_refuses())
        ) \
        .then(_it_returned_without_raising())


@pytest.mark.unit
def test_a_memory_store_that_is_down_is_said_on_the_timeline() -> None:
    # Silence would be indistinguishable from an incident that had nothing
    # worth filing, and the two call for different things from whoever reads
    # it: one is Argus working correctly, the other is Argus with a broken
    # store.
    why_it_could_not_be_written = "connection refused"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            an_incident_that_is_over := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_is_over,
                actions_taken=_actions(
                    _an_action("new-checkout-flow", Verdict.REFUTED)
                ),
                remember=_a_store_that_refuses(why_it_could_not_be_written),
                publisher=published.take)
        ) \
        .then(
            all_of(
                _an_event_of_kind_was_published(published, "remembering-failed"),
                _an_event_mentioning(published, why_it_could_not_be_written)
            )
        )


@pytest.mark.unit
def test_what_was_filed_is_said_on_the_timeline() -> None:
    # The account says what Argus did, and this is the last thing it does. A
    # record written with nothing saying so is a row whose absence, later,
    # nobody can account for.
    the_flag_that_did_not_help = "new-checkout-flow"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            an_incident_that_is_over := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_is_over,
                actions_taken=_actions(
                    _an_action(the_flag_that_did_not_help, Verdict.REFUTED)
                ),
                remember=_a_store_keeping(Kept()),
                publisher=published.take)
        ) \
        .then(
            all_of(
                _an_event_of_kind_was_published(published, "incident-remembered"),
                _an_event_mentioning(published, the_flag_that_did_not_help)
            )
        )


@pytest.mark.unit
def test_an_incident_that_filed_nothing_says_nothing() -> None:
    # No record and no line about there being no record. Nothing happened that
    # an account of the incident is missing without.
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            an_incident_that_did_nothing := _an_incident_in(IncidentStatus.ESCALATED)
        ) \
        .when(
            lambda: remembering_node(
                an_incident_that_did_nothing,
                actions_taken=_actions(),
                remember=_a_store_keeping(Kept()),
                publisher=published.take)
        ) \
        .then(_nothing_was_published(published))


def _an_incident_in(status: IncidentStatus,
                    incident_id: str = DONT_CARE_INCIDENT_ID) -> IncidentState:
    return IncidentState(
        incident_id=incident_id,
        alert=Alert(service="io-shop", alert_name="HighErrorRate"),
        status=status
    )


def _an_action(subject: str, verdict: Verdict) -> TakenAction:
    return TakenAction(
        id=DONT_CARE_INCIDENT_ID,
        incident_id=DONT_CARE_INCIDENT_ID,
        hypothesis_id=DONT_CARE_HYPOTHESIS_ID,
        type=REVERT_FEATURE_FLAG,
        subject=subject,
        reversible=True,
        undo_descriptor=None,
        outcome=verdict,
        taken_at=datetime(2026, 8, 30, 10, 14, tzinfo=UTC)
    )


def _actions(*taken: TakenAction) -> ActionsTaken:
    def actions_taken(dont_care_incident_id: str) -> list[TakenAction]:
        return list(taken)

    return actions_taken


def _a_store_keeping(filed: Kept[RememberedIncident]) -> RememberIncident:
    def remember(record: RememberedIncident) -> None:
        filed.take(record)

    return remember


def _a_store_that_refuses(refusal: str = "dont care") -> RememberIncident:
    def remember(dont_care_record: RememberedIncident) -> None:
        raise ConnectionError(refusal)

    return remember


def _filed_one_record_for(filed: Kept[RememberedIncident],
                          incident_id: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded = filed.only()

        if recorded.incident_id != incident_id:
            raise AssertionError(
                f"expected a record filed for [{incident_id}], "
                f"got [{recorded.incident_id}]")

        return True

    return assertion


def _filed_a_record_naming(filed: Kept[RememberedIncident],
                           subject: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        subjects = [attempt.subject for attempt in filed.only().tried]

        if subject not in subjects:
            raise AssertionError(f"expected [{subject}] among {subjects}")

        return True

    return assertion


def _nothing_was_filed(filed: Kept[RememberedIncident]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if filed.taken:
            raise AssertionError(f"expected nothing filed, got {filed.taken}")

        return True

    return assertion


def _it_returned_without_raising() -> Assertion[object]:
    def assertion(returned: object) -> bool:
        if returned is None:
            raise AssertionError("expected the node to return a delta, got nothing")

        return True

    return assertion


def _an_event_of_kind_was_published(published: Kept[IncidentEvent],
                                    kind: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        kinds = [event.kind for event in published.taken]

        if kind not in kinds:
            raise AssertionError(f"expected an event of kind [{kind}] among {kinds}")

        return True

    return assertion


def _an_event_mentioning(published: Kept[IncidentEvent],
                         expected: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        said = [event.model_dump_json() for event in published.taken]

        if not any(expected in one for one in said):
            raise AssertionError(f"expected [{expected}] among {said}")

        return True

    return assertion


def _nothing_was_published(published: Kept[IncidentEvent]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if published.taken:
            raise AssertionError(f"expected nothing published, got {published.taken}")

        return True

    return assertion
