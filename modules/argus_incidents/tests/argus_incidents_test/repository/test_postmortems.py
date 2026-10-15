from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    Alert,
    ChainStep,
    CitedEvidence,
    ContributingFactor,
    Detection,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    Lessons,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    ResolutionStep,
    ReviewCriterion,
    Standing,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Weighing,
)
from argus_incidents.repository import incidents, postmortems
from argus_testkit import Assertion, Scenario, all_of

from argus_incidents_test.framework import no_column_is_empty

SOME_SERVICE = "io-shop"
SOME_MOMENT = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)


@pytest.mark.integration
def test_a_document_proposing_a_fix_comes_back_naming_where_to_read_it() -> None:
    # The pull request is the only field that crosses the boundary as an object
    # rather than as a column type, so it is the only one that can come back a
    # string that merely looks like one - or fail to be written at all, which
    # is what a bare model handed to psycopg does.
    where_it_can_be_read = "https://github.invalid/ohadraz/io-shop/pull/7"

    with connect_from_env() as conn:
        incident_id = _an_incident_created_in(conn)
        a_document_proposing = _a_document(
            pull_request=OpenedPullRequest(
                number=7, url=where_it_can_be_read, branch="argus/fix-abc"
            )
        )

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_proposing)
            ) \
            .then(
                all_of(
                    _the_stored_postmortem_proposes(
                        conn, incident_id, at=where_it_can_be_read
                    ),
                    _the_stored_postmortem_numbers_the_proposal(conn, incident_id, 7)
                )
            )


@pytest.mark.integration
def test_a_document_that_proposed_no_fix_comes_back_proposing_none() -> None:
    # The ordinary ending. Null rather than an empty object, so that a page
    # asking "is there a fix to read" gets an answer rather than a shape.
    with connect_from_env() as conn:
        incident_id = _an_incident_created_in(conn)
        a_document_proposing_nothing = _a_document(pull_request=None)

        Scenario() \
            .when(
                lambda: postmortems.record(
                    conn, incident_id, a_document_proposing_nothing
                )
            ) \
            .then(
                _the_stored_postmortem_proposes_nothing(conn, incident_id)
            )


@pytest.mark.integration
def test_a_document_with_every_figure_leaves_no_column_of_its_row_empty() -> None:
    # This table cannot leave a column out - both statements are built from the
    # model's own fields, so the INSERT names whatever the document declares.
    # What it can do is name a column and write `None` into it every time,
    # which is what a field nothing ever fills looks like from here: present in
    # the statement, absent in the row, and unreadable to everybody after.
    #
    # So the document is the complete one - every figure the write-up can carry,
    # every section of the template, and the fix it proposed - and the question
    # is whether a complete document reaches the table complete.
    a_complete_document = _a_document(
        pull_request=OpenedPullRequest(
            number=7,
            url="https://github.invalid/ohadraz/io-shop/pull/7",
            branch="argus/fix-abc"
        )
    ).model_copy(update={
        "root_cause": "a feature flag was toggled on and the checkout path fell over",
        "executive_summary": "one flag, seven minutes, reverted",
        "symptom": "Checkout failed",
        "customer_loss_estimate": Decimal("1840.00"),
        "estimate_currency": "usd",
        "engineer_minutes": 7,
        "responders": 2,
        "responder_titles": ["site reliability engineer", "staff engineer"],
        "responder_cost_estimate": Decimal("31.50"),
        "responder_cost_minimum": Decimal("24.00"),
        "responder_cost_maximum": Decimal("39.00"),
        "responder_cost_currency": "usd",
        "tokens_spent": 48210,
        "assumptions": ["the published rate for the day the incident opened"],
        "recommended_action": "putting monthly-spend-feature back",
        "leads": [_a_lead_weighed_as(Standing.SUPPORTED, effect="it named the flag reverted")],
        **_every_section_of_the_template()
    })

    with connect_from_env() as conn:
        incident_id = _an_incident_created_in(conn)

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_complete_document)
            ) \
            .then(
                no_column_is_empty(conn, "postmortem", "incident_id", incident_id)
            )


@pytest.mark.integration
def test_what_people_told_the_incident_comes_back_whole() -> None:
    # A list of objects, each carrying a moment and an object of its own - the
    # one field here psycopg can neither send as it stands nor hand back as
    # what it was. A lead that came back with its standing as a string, or its
    # moment as text, would be a document saying less than it was written with.
    some_leads = [
        _a_lead_weighed_as(Standing.SUPPORTED, effect="it named the flag reverted"),
        _a_lead_weighed_as(None, effect=None)
    ]

    with connect_from_env() as conn:
        incident_id = _an_incident_created_in(conn)
        a_document_with_leads = _a_document(pull_request=None).model_copy(
            update={"leads": some_leads}
        )

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_with_leads)
            ) \
            .then(
                _the_stored_postmortem_carries_the_leads(conn, incident_id, some_leads)
            )


@pytest.mark.integration
def test_the_templates_sections_come_back_whole() -> None:
    # Every section the template adds is an object or a list of them, carrying
    # moments, enums and a duration - each a value psycopg cannot send as it
    # stands, and each one that could come back as text that merely looks like
    # what was written. Compared whole, so a section that lost a field reports
    # which one.
    some_sections = _every_section_of_the_template()

    with connect_from_env() as conn:
        incident_id = _an_incident_created_in(conn)
        a_document_with_every_section = _a_document(pull_request=None).model_copy(
            update=some_sections
        )

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_with_every_section)
            ) \
            .then(
                _the_stored_postmortem_carries_the_sections(conn, incident_id, some_sections)
            )


def _the_stored_postmortem_proposes(conn: psycopg.Connection,
                                    incident_id: str,
                                    *,
                                    at: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None or stored.pull_request is None:
            raise AssertionError(
                f"Expected a postmortem proposing [{at}], got [{stored}].")

        if stored.pull_request.url != at:
            raise AssertionError(
                f"Expected the fix at [{at}], got [{stored.pull_request.url}].")

        return True

    return assertion


def _the_stored_postmortem_numbers_the_proposal(conn: psycopg.Connection,
                                                incident_id: str,
                                                expected: int) -> Assertion[Any]:
    """The whole object came back, not just the field the page happens to show.

    Read separately from the address because they fail separately: a JSON
    column written as text comes back with every field intact and unusable,
    and one written field by field comes back missing the ones nobody asserted.
    """
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)
        numbered = stored.pull_request.number if stored and stored.pull_request else None

        if numbered != expected:
            raise AssertionError(
                f"Expected the proposal numbered [{expected}], got [{numbered}].")

        return True

    return assertion


def _the_stored_postmortem_proposes_nothing(conn: psycopg.Connection,
                                            incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("Expected a postmortem to have been written, none was.")

        if stored.pull_request is not None:
            raise AssertionError(
                f"Expected no fix proposed, got [{stored.pull_request}].")

        return True

    return assertion


def _the_stored_postmortem_carries_the_leads(conn: psycopg.Connection,
                                             incident_id: str,
                                             expected: list[PostmortemLead]
                                             ) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("Expected a postmortem to have been written, none was.")

        if stored.leads != expected:
            raise AssertionError(
                f"Expected the postmortem to carry {expected}, and it came back "
                f"carrying {stored.leads}."
            )

        return True

    return assertion


def _the_stored_postmortem_carries_the_sections(conn: psycopg.Connection,
                                                incident_id: str,
                                                expected: dict[str, Any]
                                                ) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("Expected a postmortem to have been written, none was.")

        differing = {section: getattr(stored, section)
                     for section, written in expected.items()
                     if getattr(stored, section) != written}

        if differing:
            raise AssertionError(
                f"Expected every section to come back as it was written, and "
                f"these came back otherwise: {differing}."
            )

        return True

    return assertion


def _every_section_of_the_template() -> dict[str, Any]:
    """One of everything the template adds, each with every field filled."""
    return {
        "detection": Detection(
            alerted_at=SOME_MOMENT + timedelta(minutes=2, seconds=40),
            rule="HighErrorRate",
            onset_at=SOME_MOMENT,
            gap=timedelta(minutes=2, seconds=40)
        ),
        "trigger": Trigger(
            subject="monthly-spend-feature",
            from_state="off",
            to_state="on",
            changed_at=SOME_MOMENT - timedelta(seconds=8)
        ),
        "resolution": [ResolutionStep(
            at=SOME_MOMENT + timedelta(minutes=5),
            action="turned monthly-spend-feature off",
            by="Argus",
            reversible=True,
            outcome="recovered, still in place",
            label="M1"
        )],
        "causal_chain": [ChainStep(
            text="the monthly average divides by the items bought this month",
            cites=[CitedEvidence(label="E3", text="ZeroDivisionError in monthly_average")]
        )],
        "contributing_factors": [ContributingFactor(
            text="the canary started at 40%",
            addressed_by=["AI-2"]
        )],
        "hypotheses": [HypothesisConsidered(
            summary="a flag change on account pages",
            confidence=0.8,
            result="confirmed",
            label="C1"
        )],
        "action_items": [ActionItem(
            number="AI-1",
            text="turn the flag off",
            type=ActionItemType.MITIGATE,
            owner="Argus",
            tracking="https://github.invalid/ohadraz/io-shop/pull/7",
            status=ActionItemStatus.DONE
        )],
        "lessons": Lessons(
            went_well=["the alert fired within 3 minutes"],
            went_wrong=["no test exercised an empty month"],
            got_lucky=["the fault was behind a flag"]
        ),
        "timeline": [TimelineEntry(
            at=SOME_MOMENT,
            who="Investigator",
            text="the error rate left its baseline",
            marker=TimelineMarker.IMPACT_BEGINS
        )],
        "evidence_read": 14,
        "changes_read": [CitedEvidence(label="P1",
                                       text="deploy rev-2 by someone: switched the model")],
        "log_messages_read": [CitedEvidence(label="G3fa2",
                                            text="ZeroDivisionError in monthly_average")],
        "review": [ReviewCriterion(criterion="some criterion met", met=True),
                   ReviewCriterion(criterion="some criterion left for a person", met=None)],
        "impact": Impact(duration=timedelta(minutes=47),
                         extent=ImpactExtent.AT_LEAST,
                         peak_error_rate=0.42)
    }


def _a_lead_weighed_as(standing: Standing | None, effect: str | None) -> PostmortemLead:
    """One thing a person told the incident, as the document reports it -
    weighed as `standing`, or never weighed where that is `None`."""
    return PostmortemLead(
        label="L1",
        person_id="U-some-person",
        person_name="Some Person",
        text="the kuki flag was flipped at noon",
        written_at=datetime(2026, 8, 20, 11, 5, tzinfo=UTC),
        weighing=(Weighing(standing=standing, reason="the flag history agrees")
                  if standing is not None else None),
        effect=effect
    )


def _an_incident_created_in(conn: psycopg.Connection) -> str:
    """One incident for the postmortem to belong to - the row is keyed by it."""
    return incidents.create(
        conn,
        Alert(
            service=SOME_SERVICE,
            alert_name="HighErrorRate",
            severity="critical",
            summary="dont care",
            started_at=datetime.now(UTC)
        )
    )


def _a_document(pull_request: OpenedPullRequest | None) -> PostmortemDocument:
    """A document whose only interesting field is the one under test.

    Everything else absent on purpose: what is being checked here is how one
    value crosses the boundary, and figures filled in around it would be
    asserting `writing`'s arrangement through a database.
    """
    return PostmortemDocument(
        root_cause="dont care",
        executive_summary="dont care",
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=None,
        responders=None,
        responder_titles=[],
        responder_cost_estimate=None,
        responder_cost_minimum=None,
        responder_cost_maximum=None,
        responder_cost_currency=None,
        tokens_spent=None,
        assumptions=[],
        pull_request=pull_request
    )
