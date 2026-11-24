from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
)
from core import utc_now
from core.models import Alert, ClaimedFix, ProposedFix
from core.stored import FIX_CLAIM, NewerShape, Shapes
from incident_record.repository import fix_claims
from postgres import connect_from_env

from incident_record_test.framework import written_and_rolled_back
from incident_record_test.framework.builders import an_incident_created_for

# What a step from one shape to the next writes, where no release has shipped a
# step: a value nothing here is written with, so a claim carrying it was brought
# up through the step and not read as it was stored.
SOME_TITLE_A_STEP_WROTE = "written by the step to the next shape"


@pytest.mark.integration
def test_a_claim_comes_back_whole() -> None:
    # Everything a step run again writes in place of asking the model: a
    # claim that lost a file, the commit or the reading would write another fix.
    some_claim = _a_claim("the first attempt's title")

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: fix_claims.claim(conn, incident_id, some_claim, at=utc_now()))
            ) \
            .when(
                lambda: fix_claims.get(conn, incident_id)
            ) \
            .then(
                _it_is(some_claim)
            )


@pytest.mark.integration
def test_a_claim_is_answered_with_itself_where_none_stood() -> None:
    some_claim = _a_claim("the only claim")

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: fix_claims.claim(conn, incident_id, some_claim, at=utc_now())
            ) \
            .then(
                _it_is(some_claim)
            )


@pytest.mark.integration
def test_a_second_claim_is_answered_with_the_first_and_changes_nothing() -> None:
    # The first may already be on the branch, which would refuse the second's
    # patch - so the first stands, and the second is told so rather than
    # written over it.
    the_first_claim = _a_claim("the first attempt's title")
    a_second_claim = _a_claim("the second attempt's title")
    the_first_moment = datetime(2026, 11, 24, 21, 30, 1, 123456, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: fix_claims.claim(conn, incident_id, the_first_claim,
                                                 at=the_first_moment))
            ) \
            .when(
                lambda: fix_claims.claim(conn, incident_id, a_second_claim, at=utc_now())
            ) \
            .then(all_of(
                _it_is(the_first_claim),
                _the_stored_claim_is(conn, incident_id, the_first_claim, the_first_moment)
            ))


@pytest.mark.integration
def test_an_incident_nothing_was_claimed_for_has_no_claim() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .when(
                lambda: fix_claims.get(conn, incident_id)
            ) \
            .then(
                _it_is(None)
            )


@pytest.mark.integration
def test_a_claim_rolled_back_by_its_caller_leaves_none() -> None:
    # Committing is the caller's, as with every write the walk makes.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(written_and_rolled_back(
                    conn, lambda: fix_claims.claim(conn, incident_id, _a_claim("dont care"),
                                                   at=utc_now())
                ))
            ) \
            .when(
                lambda: fix_claims.get(conn, incident_id)
            ) \
            .then(
                _it_is(None)
            )


@pytest.mark.integration
def test_a_claim_written_in_an_older_shape_is_brought_up_before_it_is_read() -> None:
    # Read with the shapes of a release one step on, which reads this
    # release's as one step behind.
    one_step_on = Shapes(upcasters={FIX_CLAIM: [_a_step_writing_the_title]})

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: fix_claims.claim(conn, incident_id, _a_claim("dont care"),
                                                 at=utc_now()))
            ) \
            .when(
                lambda: fix_claims.get(conn, incident_id, one_step_on)
            ) \
            .then(
                _its_title_is(SOME_TITLE_A_STEP_WROTE)
            )


@pytest.mark.integration
def test_a_claim_written_in_a_newer_shape_is_refused_rather_than_guessed_at() -> None:
    # Written by a release one step on, and read by this one. The claim is the
    # incident's own account of the fix it is writing: read as the shape this
    # release knows, it would be written with whatever the newer one moved in
    # the wrong field, and anything written in its place would be refused by
    # the branch the claim is already on.
    one_step_on = Shapes(upcasters={FIX_CLAIM: [_a_step_writing_the_title]})

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, _an_alert())

        Scenario() \
            .given(
                calling(lambda: fix_claims.claim(conn, incident_id, _a_claim("dont care"),
                                                 at=utc_now(), shapes=one_step_on))
            ) \
            .when(
                attempting(lambda: fix_claims.get(conn, incident_id))
            ) \
            .then(
                an_error_was_raised(NewerShape)
            )


def _the_stored_claim_is(conn: psycopg.Connection,
                         incident_id: str,
                         expected: ClaimedFix,
                         claimed_at: datetime) -> Assertion[Any]:
    """The incident's one row, read with SQL of its own - every reader asks for
    the one claim, and would find one of two."""
    def assertion(_: Any) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT claim, claimed_at FROM fix_claim WHERE incident_id = %s",
                           (incident_id,))
            rows = cursor.fetchall()

        stored = [(ClaimedFix.model_validate(claim), at) for claim, at in rows]

        if stored != [(expected, claimed_at)]:
            raise AssertionError(
                f"Expected the one claim {expected!r} claimed at [{claimed_at}], got {stored}."
            )

        return True

    return assertion


def _it_is(expected: ClaimedFix | None) -> Assertion[ClaimedFix | None]:
    def assertion(found: ClaimedFix | None) -> bool:
        if found != expected:
            raise AssertionError(f"Expected the claim {expected!r}, got {found!r}.")

        return True

    return assertion


def _its_title_is(expected: str) -> Assertion[ClaimedFix | None]:
    def assertion(found: ClaimedFix | None) -> bool:
        title = found.title if found is not None else None

        if title != expected:
            raise AssertionError(f"Expected the title [{expected}], got [{title}].")

        return True

    return assertion


def _an_alert() -> Alert:
    """The alert the incident a claim belongs to was opened by - the row is
    keyed by the incident, and nothing here reads the alert."""
    return Alert(service="dont-care", alert_name="dont-care")


def _a_claim(title: str) -> ClaimedFix:
    """A claim told apart from another by its title, every field filled - one
    lost on the way to the row and back is then one the comparison sees."""
    return ClaimedFix(
        files={"src/io_shop/spend_summary.py": "def spend(): ...\n",
               "tests/io_shop/test_spend_summary.py": "def test_spend(): ...\n"},
        base_branch="main",
        base_commit="8c1d4b07a2e95f3360d1c4e8b7a9f20e51d6c3a4",
        title=title,
        body=f"the body of the pull request titled {title}",
        brings_a_test=True,
        reading=ProposedFix(pull_request=None,
                            explanation="spend divides by the month's purchases",
                            holds_what_ran=True,
                            branch_read="main")
    )


def _a_step_writing_the_title(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "title": SOME_TITLE_A_STEP_WROTE}
