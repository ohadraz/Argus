from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, OpenedPullRequest, PostmortemDocument
from argus_incidents.repository import incidents, postmortems
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVICE = "io-shop"


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


def _the_stored_postmortem_proposes(conn: psycopg.Connection,
                                    incident_id: str,
                                    *,
                                    at: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None or stored.pull_request is None:
            raise AssertionError(
                f"expected a postmortem proposing [{at}], got [{stored}]")

        if stored.pull_request.url != at:
            raise AssertionError(
                f"expected the fix at [{at}], got [{stored.pull_request.url}]")

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
                f"expected the proposal numbered [{expected}], got [{numbered}]")

        return True

    return assertion


def _the_stored_postmortem_proposes_nothing(conn: psycopg.Connection,
                                            incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("expected a postmortem to have been written, none was")

        if stored.pull_request is not None:
            raise AssertionError(
                f"expected no fix proposed, got [{stored.pull_request}]")

        return True

    return assertion


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
        pull_request=pull_request,
        checklist_complete=True
    )
