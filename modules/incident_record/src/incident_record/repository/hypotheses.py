from __future__ import annotations

import json
from typing import Any, Final

import psycopg
from core.models import Hypothesis
from core.stored import EVIDENCE, SHIPPED, Shapes, up_to_date
from psycopg.rows import dict_row

from incident_record.walk_step import the_current_step

# What a candidate is read from: every field of it, and the shape its evidence
# was written in.
_COLUMNS: Final = (
    "id, incident_id, summary, failure_mode, confidence, "
    "supporting_evidence, shape, subject, from_state, to_state, "
    "faulting_service, rank, number, tested, result"
)


def record(conn: psycopg.Connection, hypothesis: Hypothesis) -> None:
    """Writes a hypothesis the Investigator formed.

    Takes the domain object whole rather than its fields one by one - the row
    *is* the hypothesis, so there is nothing to translate beyond the shape
    Postgres wants. The id comes from the object, not from the table's
    default: it was assigned when the hypothesis was formed. The evidence is
    written in the shape this release writes it in.

    Stamped with the walk's step it was formed in (`the_current_step`), so a
    step run again finds the candidates its interrupted attempt formed
    (`delete_by_step`). Refusing a row with no step is the walk's writer's,
    not this function's: a candidate written outside a walk is a fixture's,
    and belongs to no step.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hypothesis "
            "       (id, incident_id, summary, failure_mode, confidence, "
            "        supporting_evidence, shape, subject, from_state, to_state, "
            "        faulting_service, rank, number, tested, result, walk_step) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                hypothesis.id,
                hypothesis.incident_id,
                hypothesis.summary,
                hypothesis.failure_mode,
                hypothesis.confidence,
                # Through pydantic rather than `json.dumps` directly: what a
                # piece of evidence holds is the model's business, and an
                # instant has no JSON spelling until the model gives it one.
                json.dumps([
                    cited.model_dump(mode="json")
                    for cited in hypothesis.supporting_evidence
                ]),
                SHIPPED.current(EVIDENCE),
                hypothesis.subject,
                hypothesis.from_state,
                hypothesis.to_state,
                hypothesis.faulting_service,
                hypothesis.rank,
                hypothesis.number,
                hypothesis.tested,
                hypothesis.result,
                the_current_step(),
            ),
        )


def delete_by_step(conn: psycopg.Connection, incident_id: str, step: int) -> int:
    """Takes back every candidate one step of an incident's walk formed, and
    answers how many there were.

    For a step run again from its checkpoint, which forms its candidates again
    under ids of their own: kept, the interrupted attempt's would be a second
    set of the same numbers, and every reader of the incident's candidates
    would list both. Nothing can name one yet - an action is claimed for a
    candidate by a later step, and a later step never ran.

    Committing is the caller's, as `record`'s is.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM hypothesis WHERE incident_id = %s AND walk_step = %s",
            (incident_id, step),
        )

        return cursor.rowcount


def record_outcome(
    conn: psycopg.Connection, hypothesis_id: str, *, tested: bool, result: str
) -> None:
    """Fills in what the walk found out about a candidate it reached.

    An update rather than a second row: a candidate is written down when the
    investigation forms it, before anyone knows whether it holds, and what
    happened to it later is the same finding with its answer attached.

    `tested` and `result` travel together because either alone is ambiguous.
    "Refuted" reads as a disproven explanation and "not a mitigation Argus may
    take unasked" as an untried one, but a row carrying only one of the two
    leaves a reader guessing which of those two very different things it is
    looking at.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE hypothesis "
            "   SET tested = %s, result = %s "
            " WHERE id = %s",
            (tested, result, hypothesis_id),
        )


def get_all_by_incident(conn: psycopg.Connection,
                        incident_id: str,
                        shapes: Shapes = SHIPPED) -> list[Hypothesis]:
    """Every candidate an incident formed, in the order it formed them.

    `get_latest_by_incident` answers with one row, which is the shape that hides
    a walk: an incident resolved on its second candidate looks, through that
    lens, like an incident with a single candidate. A reader asking what the
    investigation considered needs all of them, including the ones it never
    reached - an untried candidate is a fact about the walk, not a gap in it.

    Ordered by each candidate's number (`Hypothesis.number`), which counts them
    across the incident's rounds - not by rank, which restarts with each round
    and would set a later round's best between an earlier round's own. Not by
    when each row was written either: a round's rows are written in the order
    memory left them, which is not the order they were formed and numbered in.
    `created_at` breaks a tie, between rows that never said their number.

    Each brought up to the shape its evidence is at now, and raising where one
    cannot be: an incident's candidates read in part would be told wrong.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY number, created_at",
            (incident_id,),
        )
        rows = cursor.fetchall()

    return [_a_hypothesis(row, shapes) for row in rows]


def get_latest_by_incident(conn: psycopg.Connection,
                           incident_id: str,
                           shapes: Shapes = SHIPPED) -> Hypothesis | None:
    """The best answer of the most recent investigation of an incident.

    Rank first, then recency - not recency alone. A round's candidates are
    written one per transaction, in the order memory left them, so the newest
    row of an investigation is whichever it left last - ordinarily its *weakest*
    alternative, the one that names no cause at all. Ordering by time alone
    therefore answers "what did Argus conclude?" with a reading it ranked below
    its best, and does so most confidently exactly when the model offered the
    most alternatives.

    Rank alone would be no better: an incident investigated a second time has
    two candidates ranked first, and the earlier one has already been refuted.
    Recency breaks that tie, which leaves this reading the newest round's best
    answer under both.

    `created_at` orders the rows but is not selected: it is an audit fact the
    table records, and nothing in the domain reads it.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} "
            "  FROM hypothesis "
            " WHERE incident_id = %s "
            "ORDER BY rank, created_at DESC "
            " LIMIT 1",
            (incident_id,),
        )
        row = cursor.fetchone()

    return _a_hypothesis(row, shapes) if row is not None else None


def _a_hypothesis(row: dict[str, Any], shapes: Shapes) -> Hypothesis:
    """The candidate a row of `_COLUMNS` holds, its evidence brought up to
    date before it is read."""
    shape = row.pop("shape")
    evidence = up_to_date(EVIDENCE, shape, row["supporting_evidence"], shapes)

    return Hypothesis.model_validate({**row, "supporting_evidence": evidence})
