from __future__ import annotations

from decimal import Decimal

import pytest
from agent_postmortem import PostmortemDocument
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Kept, Scenario, all_of
from orchestrator.graph import RecordPostmortem, WritePostmortem, postmortem_node

"""The last node: what it writes, and that it writes at all.

Two collaborators, both injected - one that produces the document and one that
stores it - because what this node does is exactly to join them. Everything
about how a postmortem is written belongs to the agent, and everything about
how a row is stored belongs to the repository; a test of this node that needed
either would be testing something else.

The document it stores is whatever came back, complete or not. An incident
that ends with a partial postmortem still ends with a postmortem: a page
finding nothing where one should be cannot tell "not written" from "lost".
"""

DONT_CARE_INCIDENT_ID = "e6e6e6e6-0000-4000-8000-000000000006"


@pytest.mark.unit
def test_the_document_that_was_written_is_the_one_that_is_stored() -> None:
    some_incident_id = DONT_CARE_INCIDENT_ID
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
    some_incident_id = DONT_CARE_INCIDENT_ID
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
    some_incident_id = DONT_CARE_INCIDENT_ID
    stored: Kept[tuple[str, PostmortemDocument]] = Kept()

    Scenario() \
        .given(
            a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED, some_incident_id)
        ) \
        .when(
            lambda: postmortem_node(
                a_resolved_incident,
                write=_a_writer_producing(_a_document(checklist_complete=False)),
                record=_a_recorder_into(stored))
        ) \
        .then(
            _stored_one_document_for(stored, some_incident_id)
        )


def _an_incident_in(status: IncidentStatus, incident_id: str) -> IncidentState:
    return IncidentState(
        incident_id=incident_id,
        alert=Alert(service="io-shop", alert_name="HighErrorRate"),
        status=status
    )


def _a_document(root_cause: str = "dont care",
                checklist_complete: bool = True) -> PostmortemDocument:
    return PostmortemDocument(
        root_cause=root_cause,
        executive_summary="dont care",
        customer_loss_estimate_usd=Decimal("336"),
        engineer_minutes=50,
        responders=2,
        tokens_spent=48_120,
        assumptions=[],
        checklist_complete=checklist_complete
    )


def _a_writer_producing(document: PostmortemDocument) -> WritePostmortem:
    def write(dont_care_incident_id: str) -> PostmortemDocument:
        return document

    return write


def _a_recorder_into(stored: Kept[tuple[str, PostmortemDocument]]) -> RecordPostmortem:
    def record(incident_id: str, document: PostmortemDocument) -> None:
        stored.take((incident_id, document))

    return record


def _stored_one_document_for(stored: Kept[tuple[str, PostmortemDocument]],
                             incident_id: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded_for, _ = stored.only()

        if recorded_for != incident_id:
            raise AssertionError(
                f"expected a document stored for [{incident_id}], got [{recorded_for}]")

        return True

    return assertion


def _stored_a_document_naming(stored: Kept[tuple[str, PostmortemDocument]],
                              expected: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        _, document = stored.only()

        if document.root_cause != expected:
            raise AssertionError(
                f"expected the stored document to name [{expected}], "
                f"got [{document.root_cause}]")

        return True

    return assertion
