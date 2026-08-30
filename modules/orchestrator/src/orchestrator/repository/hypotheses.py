from __future__ import annotations

import json

import psycopg
from argus_core.models.hypothesis import Hypothesis
from psycopg.rows import class_row


def record(conn: psycopg.Connection, hypothesis: Hypothesis) -> None:
    """Writes a hypothesis the Investigator formed.

    Takes the domain object whole rather than its fields one by one - the row
    *is* the hypothesis, so there is nothing to translate beyond the shape
    Postgres wants. The id comes from the object, not from the table's
    default: it was assigned when the hypothesis was formed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hypothesis "
            "       (id, incident_id, summary, cause_type, confidence, "
            "        supporting_evidence, subject, rank, tested, result) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                hypothesis.id,
                hypothesis.incident_id,
                hypothesis.summary,
                hypothesis.cause_type,
                hypothesis.confidence,
                json.dumps(hypothesis.supporting_evidence),
                hypothesis.subject,
                hypothesis.rank,
                hypothesis.tested,
                hypothesis.result,
            ),
        )
    conn.commit()


def record_outcome(
    conn: psycopg.Connection, hypothesis_id: str, *, tested: bool, result: str
) -> None:
    """Fills in what the walk found out about a candidate it reached.

    An update rather than a second row: a candidate is written down when the
    investigation forms it, before anyone knows whether it holds, and what
    happened to it later is the same finding with its answer attached.

    `tested` and `result` travel together because either alone is ambiguous.
    "Refuted" reads as a disproven explanation and "no undo descriptor" as an
    untried one, but a row carrying only one of the two leaves a reader
    guessing which of those two very different things it is looking at.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE hypothesis "
            "   SET tested = %s, result = %s "
            " WHERE id = %s",
            (tested, result, hypothesis_id),
        )
    conn.commit()


def get_all_by_incident(conn: psycopg.Connection, incident_id: str) -> list[Hypothesis]:
    """Every candidate an incident formed, best-ranked first.

    `get_latest_by_incident` answers with one row, which is the shape that hides
    a walk: an incident resolved on its second candidate looks, through that
    lens, like an incident with a single candidate. A reader asking what the
    investigation considered needs all of them, including the ones it never
    reached - an untried candidate is a fact about the walk, not a gap in it.

    Ordered by rank, with `created_at` breaking ties, so two candidates the
    Investigator ranked equally still read back in the order it formed them.
    """
    with conn.cursor(row_factory=class_row(Hypothesis)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, summary, cause_type, confidence, "
            "       supporting_evidence, subject, rank, tested, result "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY rank, created_at",
            (incident_id,),
        )
        return cursor.fetchall()


def get_latest_by_incident(conn: psycopg.Connection, incident_id: str) -> Hypothesis | None:
    """The most recent hypothesis formed for an incident.

    `created_at` orders the rows but is not selected: it is an audit fact the
    table records, and nothing in the domain reads it.
    """
    with conn.cursor(row_factory=class_row(Hypothesis)) as cursor:
        cursor.execute(
            "SELECT id, incident_id, summary, cause_type, confidence, "
            "       supporting_evidence, subject, rank, tested, result "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (incident_id,),
        )
        return cursor.fetchone()
