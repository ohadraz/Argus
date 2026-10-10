from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

import psycopg
from argus_core.models import Alert, Incident, IncidentStatus
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

# What an incident started outside any trace keeps: nothing, and nothing a
# caller could add to by holding on to the default.
NO_TRACE_CONTEXT: Final[Mapping[str, str]] = MappingProxyType({})


def create(conn: psycopg.Connection,
           alert: Alert,
           trace_context: Mapping[str, str] = NO_TRACE_CONTEXT) -> str:
    """Creates the Incident row (spec §7.1's single-writer rule, §11.1).

    `trace_context` is the trace the alert arrived in, as the propagator wrote
    it, and is what every later walk of the incident continues. Empty where
    the incident was started outside any trace.

    `acknowledged`, not `investigating`: this runs where the alert is received,
    and the walk it queues belongs to a worker that has not taken it yet.
    Writing `investigating` here would date an investigation from the moment
    Argus heard about the incident rather than from the moment one began.

    Committing is the caller's, for the reason it is `transition`'s: the line
    that accounts for this incident is published on the same connection, and a
    commit here would put the row beyond reach of its own first sentence. A
    crash between the two would otherwise leave an incident whose account
    begins nowhere."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (alert_payload, status, trace_context) "
            "VALUES (%s, %s, %s) RETURNING id",
            (Jsonb(alert.model_dump(mode="json")), IncidentStatus.ACKNOWLEDGED,
             Jsonb(dict(trace_context)))
        )
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def transition(
    conn: psycopg.Connection,
    incident_id: str,
    to_status: IncidentStatus
) -> bool:
    """Updates `Incident.status` (spec §7.1, §11.1's single-writer rule), and
    says whether it did.

    For a status the incident is actually entering. Work that is worth
    recording and moved nothing is published as the acting node's own event,
    and writes nothing here at all.

    Never over a person's ending - a withdrawal or a resolution. A person ends
    an incident from outside the walk, so the walk can be halfway through a
    step when it happens - and the step finishing afterwards would write its
    own status over that person's decision: a withdrawn incident walked on with
    nothing ever put back, or a resolved one reported as still mitigating, or
    escalated by a walk that failed after the person had already finished the
    job. The guard is in the statement rather than in a read before it,
    because a read and a write are two moments and a withdrawal can land
    between them. `False` is how the caller learns the incident was not
    moved, and that nothing is to be said about a move that did not happen.

    The status alone. What moved it, why, and how sure it was are the
    `StatusChanged` its caller publishes on this same connection - one account
    of the incident rather than a column-shaped copy of one beside it.

    A transition into a terminal status also stamps `ended_at`, in the same
    statement rather than in a second one: the two facts are one event, and a
    status written without its time would leave an incident that has ended
    looking like one still running.

    `now()` rather than a time the caller supplies - the database already
    stamps `created_at`, and a duration measured between two clocks is a
    duration measuring the difference between them.

    Committing is the caller's. The event that narrates this transition is
    written on the same connection, and a commit here would put the transition
    beyond reach of the account before the account existed.
    """
    ends_the_incident = to_status.is_terminal()
    a_persons_endings = [status for status in IncidentStatus if status.is_a_persons_ending()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident "
            "   SET status = %s, ended_at = CASE WHEN %s THEN now() ELSE ended_at END "
            " WHERE id = %s AND status <> ALL(%s)",
            (to_status, ends_the_incident, incident_id, a_persons_endings)
        )

        return cursor.rowcount == 1


def withdraw(conn: psycopg.Connection, incident_id: str) -> bool:
    """Takes an incident back from Argus, and says whether it took effect.

    The one status written from outside the walk. Every other status an
    incident reaches is derived from work the walk did and written by the walk
    itself; this one records something the walk cannot observe - that somebody
    has the failure in hand - so it is written here and the walk finds out by
    reading it back.

    The refusal is the point of the `WHERE`. An incident that resolved was
    resolved by a mitigation still holding the service up, and withdrawing it
    would put the failure back; an incident already withdrawn has had its
    actions undone once, and undoing them again would fight whoever has changed
    them since. Both are refused by the same clause, and refused in the same
    statement that would have made the change - a read followed by a write
    would let two callers both find the incident live and both withdraw it.

    The answer is what tells them apart, and callers act on it: the endpoint
    reports it, and the walk's unwind runs only for the withdrawal that took
    effect, so a second press is not a second undo.

    The account is published only where the status moved: a line claiming the
    incident entered `withdrawn` when it was already there is a claim about the
    incident that is not true.
    """
    withdrawable = [status for status in IncidentStatus if status.accepts_withdrawal()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident SET status = %s, ended_at = now() "
            " WHERE id = %s AND status = ANY(%s)",
            (IncidentStatus.WITHDRAWN, incident_id, withdrawable)
        )
        withdrawn = cursor.rowcount == 1
    conn.commit()

    return withdrawn


def resolve(conn: psycopg.Connection, incident_id: str) -> bool:
    """Records that a person reported the incident resolved, and says whether
    it took effect.

    Written here rather than derived by the walk, for the reason a withdrawal
    is: the walk never concludes `resolved` (spec §10), and what this records -
    that somebody finished the job - is a fact its own state cannot hold. The
    walk finds out by reading it back.

    Accepted from every status `accepts_resolution` names, the terminal endings
    Argus reached by stopping included, and refused for the rest in the same
    statement that would have made the change - a read followed by a write
    would let the walk land a status in between.

    The end an incident already had is kept. Argus having escalated it is when
    its part ended, the postmortem was written to that end and is not
    rewritten, and an end restamped here would put the document out of step
    with its own durations. An incident still running ends now.

    Commits, as `withdraw` does: the caller is a door outside the walk, with no
    transaction of its own for this to join.
    """
    resolvable = [status for status in IncidentStatus if status.accepts_resolution()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident SET status = %s, ended_at = COALESCE(ended_at, now()) "
            " WHERE id = %s AND status = ANY(%s)",
            (IncidentStatus.RESOLVED, incident_id, resolvable)
        )
        resolved = cursor.rowcount == 1
    conn.commit()

    return resolved


def get_recent(conn: psycopg.Connection) -> list[Incident]:
    """Every incident, newest first.

    A history view opens on what just happened, so the ordering is the whole
    point of the name: oldest-first would put the incident somebody came looking
    for at the bottom of the page.
    """
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, created_at, ended_at, trace_context "
            "  FROM incident "
            "ORDER BY created_at DESC"
        )
        return cursor.fetchall()


def get_current(conn: psycopg.Connection) -> Incident | None:
    """The incident a live view opens on: the newest one that has not finished,
    and where none is running, the newest there has ever been.

    No stored pointer to a "current" incident, because a pointer is a second
    thing that can be wrong about which incident is running. The rule is a
    question the rows already answer, and it is right whenever one incident
    runs at a time - which is what the demo does, and what it degrades from
    sensibly rather than by showing nothing.

    The fallback matters as much as the rule. An incident that vanished from
    the front page the moment it resolved would leave the screen exactly when
    everybody in the room is looking at it.

    Ordering on the terminal statuses rather than filtering by them, so the
    whole rule is one query: `false` sorts before `true`, which puts every
    unfinished incident above every finished one, newest first within each.
    """
    terminal = [status for status in IncidentStatus if status.is_terminal()]

    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, created_at, ended_at, trace_context "
            "  FROM incident "
            "ORDER BY status = ANY(%s), created_at DESC "
            " LIMIT 1",
            (terminal,)
        )
        return cursor.fetchone()


def get_open_by_rule_and_service(conn: psycopg.Connection,
                                 rule: str,
                                 service: str) -> Incident | None:
    """The newest unfinished incident `rule` opened for `service`, if any.

    What a rule firing again while Argus is still on its incident joins: the
    incident going on rather than a second one beside it. Finished incidents are
    not looked at - once one is over, the rule firing again is a new incident.
    Nor are other services': a rule watching several pages for each, and the
    service paged for is what an incident investigates.
    """
    still_going = [status for status in IncidentStatus if not status.is_terminal()]

    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, created_at, ended_at, trace_context "
            "  FROM incident "
            " WHERE alert_payload->>'rule' = %s "
            "   AND alert_payload->>'service' = %s "
            "   AND status = ANY(%s) "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (rule, service, still_going)
        )
        return cursor.fetchone()


def get(conn: psycopg.Connection, incident_id: str) -> Incident | None:
    with conn.cursor(row_factory=class_row(Incident)) as cursor:
        cursor.execute(
            "SELECT id, alert_payload, status, created_at, ended_at, trace_context "
            "  FROM incident "
            " WHERE id = %s",
            (incident_id,)
        )
        return cursor.fetchone()
