from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env, utc_now
from argus_core.models import Alert, ExecutiveSynopsisDocument, TitleCost
from argus_incidents.repository import synopses
from argus_testkit import Assertion, Scenario

from argus_incidents_test.framework import no_column_is_empty
from argus_incidents_test.framework.builders import an_incident_created_for


@pytest.mark.integration
def test_a_complete_synopsis_leaves_no_column_of_its_row_empty() -> None:
    # Both statements are built from the model's own fields, as the
    # postmortem's are, so the question is not whether a column is named but
    # whether a complete synopsis reaches its row complete.
    dont_care_overview = "dont care"
    dont_care_reason = "dont care"
    dont_care_title = "dont care"
    dont_care_shared_page = "dont care"
    a_complete_synopsis = ExecutiveSynopsisDocument(
        overview=dont_care_overview,
        withheld_because=dont_care_reason,
        cost_by_title=[_a_priced_row(dont_care_title)],
        breakdown_unmatched=True,
        response_shared=dont_care_shared_page
    )

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: synopses.record(conn, incident_id, a_complete_synopsis, at=utc_now())
            ) \
            .then(
                no_column_is_empty(conn, "executive_synopsis", "incident_id", incident_id)
            )


@pytest.mark.integration
def test_a_synopsis_is_dated_by_the_moment_given() -> None:
    # The moment of the event saying it was written, as with the postmortem:
    # one instant on one clock wherever it is said.
    some_moment = datetime(2026, 11, 9, 19, 14, 9, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: synopses.record(conn, incident_id, _a_synopsis(), at=some_moment)
            ) \
            .then(
                _the_stored_synopsis_was_written_at(conn, incident_id, some_moment)
            )


@pytest.mark.integration
def test_a_withheld_synopsis_comes_back_withheld_and_saying_why() -> None:
    # No overview is the one state that posts nothing, so it has to come back
    # as no overview - not an empty string the relay would post.
    some_reason = "the overview was refused twice: it wrote out a figure"
    a_withheld_synopsis = _a_synopsis().model_copy(
        update={"overview": None, "withheld_because": some_reason}
    )

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: synopses.record(conn, incident_id, a_withheld_synopsis, at=utc_now())
            ) \
            .then(
                _the_stored_synopsis_is_withheld_because(conn, incident_id, some_reason)
            )


@pytest.mark.integration
def test_the_cost_by_title_comes_back_whole() -> None:
    # A list of objects carrying amounts, a missing title and missing amounts -
    # each of which can come back as something else: a Decimal as a float, a
    # `None` title as the string "None", an unpriced row as zero.
    some_title = "site reliability engineer"
    some_other_title = "principal engineer"
    some_rows = [
        _a_priced_row(some_title),
        _a_priced_row(None),
        _an_unpriced_row(some_other_title)
    ]

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_synopsis_with_rows = _a_synopsis().model_copy(update={"cost_by_title": some_rows})

        Scenario() \
            .when(
                lambda: synopses.record(conn, incident_id, a_synopsis_with_rows, at=utc_now())
            ) \
            .then(
                _the_stored_synopsis_carries_the_rows(conn, incident_id, some_rows)
            )


@pytest.mark.integration
def test_an_incident_with_no_synopsis_has_none() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: synopses.get_by_incident(conn, incident_id)
            ) \
            .then(
                _nothing()
            )


def _the_stored_synopsis_was_written_at(conn: psycopg.Connection,
                                        incident_id: str,
                                        moment: datetime) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = synopses.get_by_incident(conn, incident_id)
        written_at = stored.created_at if stored is not None else None

        if written_at != moment:
            raise AssertionError(
                f"Expected the synopsis to be written at [{moment}], got [{written_at}].")

        return True

    return assertion


def _the_stored_synopsis_is_withheld_because(conn: psycopg.Connection,
                                             incident_id: str,
                                             reason: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = synopses.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("Expected a synopsis to have been written, none was.")

        if stored.overview is not None or stored.withheld_because != reason:
            raise AssertionError(
                f"Expected no overview, withheld because [{reason}], got the overview "
                f"[{stored.overview}] withheld because [{stored.withheld_because}].")

        return True

    return assertion


def _the_stored_synopsis_carries_the_rows(conn: psycopg.Connection,
                                          incident_id: str,
                                          expected: list[TitleCost]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = synopses.get_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError("Expected a synopsis to have been written, none was.")

        if stored.cost_by_title != expected:
            raise AssertionError(
                f"Expected the synopsis to carry {expected}, and it came back carrying "
                f"{stored.cost_by_title}.")

        return True

    return assertion


def _nothing() -> Assertion[Any]:
    def assertion(found: Any) -> bool:
        if found is not None:
            raise AssertionError(f"Expected no synopsis, got {found}.")

        return True

    return assertion


def _an_alert() -> Alert:
    """The alert the incident a synopsis belongs to was opened by - the row is
    keyed by the incident, and nothing here reads the alert."""
    return Alert(service="dont-care", alert_name="dont-care")


def _a_priced_row(title: str | None) -> TitleCost:
    """A title's row priced to four places, with its bottom and top either side
    of its midpoint - the places a Decimal that came back a float would lose."""
    midpoint = Decimal("11.6667")
    spread = Decimal("2.77")
    return TitleCost(title=title, responders=2, minutes=14,
                     midpoint=midpoint, minimum=midpoint - spread,
                     maximum=midpoint + spread)


def _an_unpriced_row(title: str) -> TitleCost:
    """A title no band prices: its people and minutes known, its amounts not."""
    return TitleCost(title=title, responders=1, minutes=9,
                     midpoint=None, minimum=None, maximum=None)


def _a_synopsis() -> ExecutiveSynopsisDocument:
    """A synopsis whose only interesting field is the one under test."""
    return ExecutiveSynopsisDocument(
        overview="dont care",
        withheld_because=None,
        cost_by_title=[],
        breakdown_unmatched=False
    )
