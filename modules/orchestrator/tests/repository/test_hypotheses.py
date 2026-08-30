from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import hypotheses, incidents

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"


@pytest.mark.integration
def test_a_recorded_hypothesis_comes_back_with_the_evidence_it_was_formed_from() -> None:
    # The evidence is the only field that crosses the boundary as JSON rather
    # than as a column type, so it is the only one that can come back a string
    # that merely looks like a list.
    some_evidence = [
        "2026-08-20T11:05:00Z WARN target-service: flag 'checkout-v2' toggled on",
        "2026-08-20T11:06:00Z ERROR target-service: request failed",
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        some_hypothesis = _a_determined_hypothesis(incident_id, some_evidence)
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .when(
                lambda: hypotheses.record(conn, some_hypothesis)
            ) \
            .then(
                the_stored_hypothesis_is(some_hypothesis)
            )


@pytest.mark.integration
def test_an_undetermined_hypothesis_comes_back_naming_no_cause() -> None:
    # Both nullable columns are null together. If either came back as a
    # default - 0.0, an empty string - the model's own validator would reject
    # the row on the way out, which is the failure this guards.
    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        an_unexplained_hypothesis = _an_undetermined_hypothesis(incident_id)
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)
        the_stored_hypothesis_names_no_cause = partial(
            _the_stored_hypothesis_names_no_cause, conn, incident_id
        )

        Scenario() \
            .when(
                lambda: hypotheses.record(conn, an_unexplained_hypothesis)
            ) \
            .then(all_of(
                the_stored_hypothesis_is(an_unexplained_hypothesis),
                the_stored_hypothesis_names_no_cause(),
            ))


@pytest.mark.integration
def test_a_hypothesis_comes_back_naming_the_subject_it_blamed() -> None:
    # The record of an incident should say *what* was blamed, not only that
    # something was. It is also what a later phase reads to act - a subject
    # that survived the model and then died in the table would leave the
    # reasoning intact and the conclusion gone.
    some_flag = "monthly-spend-feature"

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        some_hypothesis = _a_determined_hypothesis(
            incident_id, ["some log line"], subject=some_flag
        )
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .when(
                lambda: hypotheses.record(conn, some_hypothesis)
            ) \
            .then(
                the_stored_hypothesis_is(some_hypothesis)
            )


@pytest.mark.integration
def test_a_hypothesis_comes_back_at_the_rank_it_was_recorded_at() -> None:
    # An investigation that named several explanations wrote them down in its
    # own order, best first. Rows come back from a table in no order at all, so
    # that ordering only survives as data - and a rank that died in the table
    # would leave a walk trying the candidates in whatever order Postgres felt
    # like returning them.
    a_third_choice = 3

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        some_hypothesis = _a_determined_hypothesis(
            incident_id, ["some log line"], rank=a_third_choice
        )
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .when(
                lambda: hypotheses.record(conn, some_hypothesis)
            ) \
            .then(
                the_stored_hypothesis_is(some_hypothesis)
            )


@pytest.mark.integration
def test_a_candidate_the_walk_reached_comes_back_carrying_what_happened_to_it() -> None:
    # A candidate is written down when the investigation forms it, before
    # anyone knows whether it holds. What the walk found out arrives later and
    # belongs on the same row: a list of explanations with no record of which
    # were tried is a list a human cannot read the incident from.
    some_result = "refuted"

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        a_candidate = _a_determined_hypothesis(incident_id, ["some log line"])
        a_hypothesis_was_recorded = partial(_a_hypothesis_was_recorded, conn)
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .given(
                a_hypothesis_was_recorded(a_candidate)
            ) \
            .when(
                lambda: hypotheses.record_outcome(
                    conn, a_candidate.id, tested=True, result=some_result
                )
            ) \
            .then(
                the_stored_hypothesis_is(
                    a_candidate.model_copy(update={"tested": True, "result": some_result})
                )
            )


@pytest.mark.integration
def test_a_candidate_that_was_never_tried_comes_back_saying_why() -> None:
    # The gate refusing an action is not the candidate being wrong; it is the
    # candidate never having been put to the question. The row has to tell
    # those two apart, or an explanation nobody tested reads afterwards like
    # one that was tested and failed.
    some_reason = "no reversible action was proposed for this cause"

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        an_untried_candidate = _a_determined_hypothesis(incident_id, ["some log line"])
        a_hypothesis_was_recorded = partial(_a_hypothesis_was_recorded, conn)
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .given(
                a_hypothesis_was_recorded(an_untried_candidate)
            ) \
            .when(
                lambda: hypotheses.record_outcome(
                    conn, an_untried_candidate.id, tested=False, result=some_reason
                )
            ) \
            .then(
                the_stored_hypothesis_is(
                    an_untried_candidate.model_copy(
                        update={"tested": False, "result": some_reason}
                    )
                )
            )


@pytest.mark.integration
def test_the_latest_hypothesis_for_an_incident_is_the_one_returned() -> None:
    # An incident can be investigated more than once; "latest" is what the
    # orchestrator reads back, so the order has to be the write order.
    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        incident_id = an_incident_created_for(_an_alert())
        the_first_hypothesis = _a_determined_hypothesis(incident_id, ["an early guess"])
        the_second_hypothesis = _a_determined_hypothesis(incident_id, ["a later guess"])
        a_hypothesis_was_recorded = partial(_a_hypothesis_was_recorded, conn)
        the_stored_hypothesis_is = partial(_the_stored_hypothesis_is, conn, incident_id)

        Scenario() \
            .given(
                a_hypothesis_was_recorded(the_first_hypothesis)
            ) \
            .when(
                lambda: hypotheses.record(conn, the_second_hypothesis)
            ) \
            .then(
                the_stored_hypothesis_is(the_second_hypothesis)
            )


@pytest.mark.integration
def test_an_incident_with_no_hypothesis_has_none_to_return() -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = _an_incident_created_for(conn, _an_alert())

        assert hypotheses.get_latest_by_incident(conn, incident_id) is None


def _an_alert() -> Alert:
    return Alert(service="kuki-service", alert_name="HighErrorRate")


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _a_determined_hypothesis(incident_id: str,
                             evidence: list[str],
                             subject: str | None = None,
                             rank: int = 1) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary="a feature flag was toggled on just before the errors began",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.94,
        supporting_evidence=evidence,
        subject=subject,
        rank=rank,
    )


def _an_undetermined_hypothesis(incident_id: str) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary="no cause determined from the evidence retrieved",
        cause_type=None,
        confidence=None,
        supporting_evidence=["2026-08-20T11:06:00Z ERROR target-service: request failed"],
    )


def _a_hypothesis_was_recorded(
    conn: psycopg.Connection, hypothesis: Hypothesis
) -> Callable[[], None]:
    def step() -> None:
        hypotheses.record(conn, hypothesis)

    return step


def _the_stored_hypothesis_is(
    conn: psycopg.Connection, incident_id: str, expected: Hypothesis
) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        stored = hypotheses.get_latest_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError(f"No hypothesis found for incident [{incident_id}].")

        if stored != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{stored!r}].")

        return True

    return assertion


def _the_stored_hypothesis_names_no_cause(
    conn: psycopg.Connection, incident_id: str
) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        stored = hypotheses.get_latest_by_incident(conn, incident_id)

        if stored is None:
            raise AssertionError(f"No hypothesis found for incident [{incident_id}].")

        if stored.cause_type is not None or stored.confidence is not None:
            raise AssertionError(
                f"Expected no cause and no confidence, got "
                f"cause_type=[{stored.cause_type!r}], confidence=[{stored.confidence!r}]."
            )

        return True

    return assertion
