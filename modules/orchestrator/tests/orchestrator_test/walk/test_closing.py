"""The last two nodes: what each writes, and that it writes at all.

Two collaborators each, both injected - one that produces the document and one
that stores it - because what each node does is exactly to join them.
Everything about how a postmortem or a synopsis is written belongs to the
agent, and everything about how a row is stored belongs to the repository; a
test of either node that needed either would be testing something else.

The document stored is whatever came back, complete or not. An incident that
ends with a partial postmortem still ends with a postmortem: a page finding
nothing where one should be cannot tell "not written" from "lost". A synopsis
given up is stored too, so the timeline can say why nothing was sent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_core.models import (
    Alert,
    ExecutiveSynopsisDocument,
    IncidentStatus,
    PostmortemDocument,
    ReviewCriterion,
)
from argus_testkit import Assertion, Kept, Scenario, all_of
from orchestrator.walk.closing import postmortem_node, synopsis_node
from orchestrator.walk.ports import (
    RecordPostmortem,
    RecordSynopsis,
    WritePostmortem,
    WriteSynopsis,
)
from orchestrator.walk.state import IncidentState

SOME_INCIDENT_ID = "e6e6e6e6-0000-4000-8000-000000000006"

# What a synopsis said, and why another was given up - each stored as it came.
SOME_OVERVIEW = "Checkout failed for 7m 12s."
SOME_REASON = "the overview was refused twice"


@pytest.mark.unit
def test_the_document_that_was_written_is_the_one_that_is_stored() -> None:
    some_incident_id = SOME_INCIDENT_ID
    some_root_cause = "the checkout fallback was disabled by a flag toggle"
    stored: Kept[tuple[str, PostmortemDocument]] = Kept()

    Scenario() \
        .given(
            a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED, some_incident_id)
        ) \
        .when(
            lambda: postmortem_node(
                a_resolved_incident,
                write=_a_writer_producing(_a_document(root_cause=some_root_cause)),
                record=_a_recorder_into(stored))
        ) \
        .then(
            all_of(
                _stored_one_document_for(stored, some_incident_id),
                _stored_a_document_naming(stored, some_root_cause)
            )
        )


@pytest.mark.unit
def test_an_escalated_incident_is_written_up_too() -> None:
    # The incident nobody could resolve is the one a person is about to pick
    # up cold, so it is the one most worth writing down - and the easiest to
    # skip, because there is no conclusion to report.
    some_incident_id = SOME_INCIDENT_ID
    stored: Kept[tuple[str, PostmortemDocument]] = Kept()

    Scenario() \
        .given(
            an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED, some_incident_id)
        ) \
        .when(
            lambda: postmortem_node(
                an_escalated_incident,
                write=_a_writer_producing(_a_document()),
                record=_a_recorder_into(stored))
        ) \
        .then(
            _stored_one_document_for(stored, some_incident_id)
        )


@pytest.mark.unit
def test_a_partial_document_is_stored_rather_than_discarded() -> None:
    some_incident_id = SOME_INCIDENT_ID
    stored: Kept[tuple[str, PostmortemDocument]] = Kept()

    Scenario() \
        .given(
            a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED, some_incident_id)
        ) \
        .when(
            lambda: postmortem_node(
                a_resolved_incident,
                write=_a_writer_producing(_a_document(review=[
                    ReviewCriterion(criterion="some criterion", met=False)])),
                record=_a_recorder_into(stored))
        ) \
        .then(
            _stored_one_document_for(stored, some_incident_id)
        )


@pytest.mark.unit
@pytest.mark.parametrize("a_synopsis", [
    ExecutiveSynopsisDocument(overview=SOME_OVERVIEW),
    ExecutiveSynopsisDocument(overview=None, withheld_because=SOME_REASON)
], ids=["written", "given-up"])
def test_the_synopsis_that_was_written_is_the_one_that_is_stored(
    a_synopsis: ExecutiveSynopsisDocument
) -> None:
    # Given up is stored too: the record is what says it was withheld, and why.
    some_incident_id = SOME_INCIDENT_ID
    stored: Kept[tuple[str, ExecutiveSynopsisDocument]] = Kept()

    Scenario() \
        .given(
            a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED, some_incident_id)
        ) \
        .when(
            lambda: synopsis_node(
                a_resolved_incident,
                write=_a_synopsis_writer_producing(a_synopsis),
                record=_a_synopsis_recorder_into(stored))
        ) \
        .then(
            _stored_one_synopsis(stored, some_incident_id, a_synopsis)
        )


def _an_incident_in(status: IncidentStatus, incident_id: str) -> IncidentState:
    return IncidentState(
        incident_id=incident_id,
        alert=Alert(service="io-shop", alert_name="HighErrorRate"),
        status=status
    )


def _a_document(root_cause: str = "dont care",
                review: list[ReviewCriterion] | None = None) -> PostmortemDocument:
    return PostmortemDocument(
        root_cause=root_cause,
        executive_summary="dont care",
        customer_loss_estimate=Decimal("336"),
        estimate_currency="usd",
        engineer_minutes=50,
        responders=2,
        tokens_spent=48_120,
        assumptions=[],
        review=review if review is not None else []
    )


def _a_writer_producing(document: PostmortemDocument) -> WritePostmortem:
    def write(dont_care_incident_id: str) -> PostmortemDocument:
        return document

    return write


def _a_recorder_into(stored: Kept[tuple[str, PostmortemDocument]]) -> RecordPostmortem:
    def record(incident_id: str, document: PostmortemDocument) -> None:
        stored.take((incident_id, document))

    return record


def _a_synopsis_writer_producing(synopsis: ExecutiveSynopsisDocument) -> WriteSynopsis:
    def write(dont_care_incident_id: str) -> ExecutiveSynopsisDocument:
        return synopsis

    return write


def _a_synopsis_recorder_into(
    stored: Kept[tuple[str, ExecutiveSynopsisDocument]]
) -> RecordSynopsis:
    def record(incident_id: str, synopsis: ExecutiveSynopsisDocument) -> None:
        stored.take((incident_id, synopsis))

    return record


def _stored_one_document_for(stored: Kept[tuple[str, PostmortemDocument]],
                             incident_id: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded_for, _ = stored.only()

        if recorded_for != incident_id:
            raise AssertionError(
                f"Expected a document stored for [{incident_id}], got [{recorded_for}].")

        return True

    return assertion


def _stored_a_document_naming(stored: Kept[tuple[str, PostmortemDocument]],
                              expected: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        _, document = stored.only()

        if document.root_cause != expected:
            raise AssertionError(
                f"Expected the stored document to name [{expected}], "
                f"got [{document.root_cause}].")

        return True

    return assertion


def _stored_one_synopsis(stored: Kept[tuple[str, ExecutiveSynopsisDocument]],
                         incident_id: str,
                         expected: ExecutiveSynopsisDocument) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if stored.only() != (incident_id, expected):
            raise AssertionError(
                f"Expected the synopsis {expected} stored for [{incident_id}], "
                f"got {stored.only()}.")

        return True

    return assertion
