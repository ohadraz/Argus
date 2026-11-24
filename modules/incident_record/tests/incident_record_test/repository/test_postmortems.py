from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, the_answer_was
from core import utc_now
from core.models import (
    Alert,
    ChannelReading,
    Postmortem,
    PostmortemDocument,
    PostmortemLead,
    Standing,
)
from core.stored import POSTMORTEM, Shapes
from incident_record.repository import postmortems
from postgres import connect_from_env

from incident_record_test.framework import no_column_is_empty, written_and_rolled_back
from incident_record_test.framework.assertions import each_field_of
from incident_record_test.framework.builders import (
    a_lead_weighed_as,
    a_postmortem_document,
    a_postmortem_document_with_every_field,
    an_incident_created_for,
    an_opened_pull_request,
    every_section_of_the_template,
)

# What a step from one shape to the next writes, where no release has shipped a
# step: a value nothing here is written with, so a row carrying it was brought
# up through the step and not read as it was stored.
SOME_CAUSE_A_STEP_WROTE = "written by the step to the next shape"


@pytest.mark.integration
def test_a_document_proposing_a_fix_comes_back_naming_where_to_read_it() -> None:
    # The pull request is the only field that crosses the boundary as an object
    # rather than as a column type, so it is the only one that can come back a
    # string that merely looks like one - or fail to be written at all, which
    # is what a bare model handed to psycopg does.
    some_pull_request = an_opened_pull_request()

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_document_proposing = a_postmortem_document(pull_request=some_pull_request)

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_proposing, at=utc_now())
            ) \
            .then(
                all_of(
                    _the_stored_postmortem_proposes(
                        conn, incident_id, at=some_pull_request.url
                    ),
                    _the_stored_postmortem_numbers_the_proposal(
                        conn, incident_id, some_pull_request.number
                    )
                )
            )


@pytest.mark.integration
def test_a_document_is_dated_by_the_moment_given() -> None:
    # The moment of the line saying it was written: the page's author line and
    # the account's line are one instant. To the microsecond, so a column that
    # kept less would show.
    moment_to_the_microsecond = datetime(2026, 10, 21, 19, 14, 9, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_postmortem_document(),
                                           at=moment_to_the_microsecond)
            ) \
            .then(
                _the_stored_postmortem_was_written_at(conn, incident_id,
                                                      moment_to_the_microsecond)
            )


@pytest.mark.integration
def test_a_document_that_proposed_no_fix_comes_back_proposing_none() -> None:
    # The ordinary ending. Null rather than an empty object, so that a page
    # asking "is there a fix to read" gets an answer rather than a shape.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_document_proposing_nothing = a_postmortem_document(pull_request=None)

        Scenario() \
            .when(
                lambda: postmortems.record(
                    conn, incident_id, a_document_proposing_nothing,
                    at=utc_now()
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
    # So the document is the complete one, and the question is whether a
    # complete document reaches the table complete.
    a_complete_document = a_postmortem_document_with_every_field()

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_complete_document, at=utc_now())
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
    some_standing = Standing.SUPPORTED
    some_effect = "it named the flag reverted"
    some_leads = [
        a_lead_weighed_as(some_standing, effect=some_effect),
        a_lead_weighed_as(None, effect=None)
    ]

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_document_with_leads = a_postmortem_document(leads=some_leads)

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_with_leads, at=utc_now())
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
    some_sections = every_section_of_the_template()

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_document_with_every_section = a_postmortem_document(**some_sections)

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_with_every_section,
                                           at=utc_now())
            ) \
            .then(
                _the_stored_postmortem_carries_the_sections(conn, incident_id, some_sections)
            )


@pytest.mark.integration
def test_what_came_of_each_read_comes_back_as_it_was_written() -> None:
    # Text in the column and an enum on the way back. One that came back a
    # string would still compare equal, and be a document saying less than it
    # was written with. Three different readings, so one written into another's
    # column shows.
    some_deploys_reading = ChannelReading.UNANSWERED
    some_flags_reading = ChannelReading.ONLY_SINCE_ARGUS_ACTED
    some_logs_reading = ChannelReading.NOT_ASKED

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())
        a_document_with_readings = a_postmortem_document(deploys_reading=some_deploys_reading,
                                                         flags_reading=some_flags_reading,
                                                         logs_reading=some_logs_reading)

        Scenario() \
            .when(
                lambda: postmortems.record(conn, incident_id, a_document_with_readings,
                                           at=utc_now())
            ) \
            .then(
                _the_stored_postmortem_read(conn, incident_id, (some_deploys_reading,
                                                                some_flags_reading,
                                                                some_logs_reading))
            )


@pytest.mark.integration
def test_a_document_rolled_back_by_its_caller_leaves_none_recorded() -> None:
    # Committing is the caller's. A document that committed on its own would
    # stand after its caller rolled back, and the page would show a write-up no
    # account says was written.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(written_and_rolled_back(
                    conn, lambda: postmortems.record(conn, incident_id, a_postmortem_document(),
                                                     at=utc_now())
                ))
            ) \
            .when(
                lambda: postmortems.get_by_incident(conn, incident_id)
            ) \
            .then(
                the_answer_was(None)
            )


@pytest.mark.integration
def test_a_document_written_in_an_older_shape_is_brought_up_before_it_is_read() -> None:
    # Every column together, through the steps after the shape it was written
    # in. Read with the shapes of a release one step on, which reads this
    # release's as one step behind.
    one_step_on = Shapes(upcasters={POSTMORTEM: [_a_step_writing_the_cause]})

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: postmortems.record(conn, incident_id, a_postmortem_document(),
                                                   at=utc_now()))
            ) \
            .when(
                lambda: postmortems.get_by_incident(conn, incident_id, one_step_on)
            ) \
            .then(
                _its_root_cause_is(SOME_CAUSE_A_STEP_WROTE)
            )


@pytest.mark.unit
def test_the_columns_written_are_the_documents_fields() -> None:
    # Named in the repository rather than read off the model, so a field
    # renamed cannot leave its column behind - and held to the model here, so
    # one added is not left unwritten.
    Scenario() \
        .when(lambda: postmortems.DOCUMENT_COLUMNS) \
        .then(each_field_of(PostmortemDocument))


def _the_stored_postmortem_was_written_at(conn: psycopg.Connection,
                                          incident_id: str,
                                          moment: datetime) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)
        written_at = stored.created_at if stored is not None else None

        if written_at != moment:
            raise AssertionError(
                f"Expected the postmortem to be written at [{moment}], got [{written_at}].")

        return True

    return assertion


def _the_stored_postmortem_read(conn: psycopg.Connection,
                                incident_id: str,
                                expected: tuple[ChannelReading, ...]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        stored = postmortems.get_by_incident(conn, incident_id)
        read = ((stored.deploys_reading, stored.flags_reading, stored.logs_reading)
                if stored is not None else None)

        if (read is None or read != expected
                or not all(isinstance(reading, ChannelReading) for reading in read)):
            raise AssertionError(
                f"Expected the deploys, the flags and the logs read as {expected!r}, "
                f"got {read!r}.")

        return True

    return assertion


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
                                                expected: Mapping[str, object]
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


def _an_alert() -> Alert:
    """The alert the incident a postmortem belongs to was opened by - the row
    is keyed by the incident, and nothing here reads the alert."""
    return Alert(service="dont-care", alert_name="dont-care")


def _a_step_writing_the_cause(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "root_cause": SOME_CAUSE_A_STEP_WROTE}


def _its_root_cause_is(expected: str) -> Assertion[Postmortem | None]:
    def assertion(stored: Postmortem | None) -> bool:
        cause = stored.root_cause if stored is not None else None

        if cause != expected:
            raise AssertionError(f"Expected the root cause [{expected}], got [{cause}].")

        return True

    return assertion
