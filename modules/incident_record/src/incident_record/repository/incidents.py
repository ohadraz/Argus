from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

import psycopg
from core.models import Alert, Incident, IncidentStanding, IncidentStatus
from core.stored import ALERT, SHIPPED, Shapes, Unreadable, up_to_date
from core.telemetry import ARGUS_INCIDENT_ID
from psycopg.rows import class_row, dict_row
from psycopg.types.json import Jsonb

from incident_record.repository.advisory_locks import AdvisoryLock

logger = logging.getLogger(__name__)

# What an incident started outside any trace keeps: nothing, and nothing a
# caller could add to by holding on to the default.
NO_TRACE_CONTEXT: Final[Mapping[str, str]] = MappingProxyType({})

# What a whole incident is read from: where it stands, and its alert with the
# shape it was written in.
_INCIDENT_COLUMNS: Final = (
    "id, status, created_at, ended_at, alert_payload, shape, trace_context"
)
# What where an incident stands is read from, and nothing a lookup that
# decides by it does not read.
_STANDING_COLUMNS: Final = "id, status, created_at, ended_at"


def take_in_alone(conn: psycopg.Connection, service: str) -> None:
    """Waits until no other transaction is taking in an alert for `service`,
    then holds that off until this transaction ends.

    Whether an alert opens an incident or joins one is decided by what is
    already there, so two deliveries deciding at once would each find nothing
    and open two. One at a time, the second finds the first's incident.

    By service alone, not by rule as well: a reminder of a firing names no rule,
    and must wait for the delivery of that firing all the same.

    Held by the transaction rather than the session, so it is let go at the
    commit or the rollback. A process keeps its connections between requests,
    and a hold that lasted as long as the connection would keep the service's
    alerts waiting on a connection nobody is using. Two services whose names
    hash alike wait for each other - never two incidents for one fault.
    """
    conn.execute(
        f"SELECT pg_advisory_xact_lock({int(AdvisoryLock.INTAKE_FOR_A_SERVICE)}, hashtext(%s))",
        (service,)
    )


def create(conn: psycopg.Connection,
           alert: Alert,
           trace_context: Mapping[str, str] = NO_TRACE_CONTEXT,
           *,
           at: datetime) -> str:
    """Creates the Incident row (spec §7.1's single-writer rule, §11.1).

    `at` is the moment of the event that opens the incident's account, so the
    row and the account are on one clock: every reader that measures from the
    row - the page's elapsed time, the postmortem's durations - measures what
    the account says. Required, and the column has no default: a row stamped
    by the database's own clock instead is the two clocks disagreeing again.

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
    begins nowhere.

    The alert is written in the shape this release writes it in, and its rule
    and service beside it, which are what an incident is looked up by."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (alert_payload, shape, alert_rule, alert_service, "
            "                      status, trace_context, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (Jsonb(alert.model_dump(mode="json")), SHIPPED.current(ALERT),
             alert.rule, alert.service, IncidentStatus.ACKNOWLEDGED,
             Jsonb(dict(trace_context)), at)
        )
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def transition(
    conn: psycopg.Connection,
    incident_id: str,
    to_status: IncidentStatus,
    *,
    at: datetime
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
    looking like one still running. A transition into any other status clears
    it, for the same reason the other way round: a walk's step run again from
    its checkpoint can take a different road than its interrupted attempt -
    on from `disproven` to `mitigating` - and an incident still being worked
    must not carry the end the first attempt wrote.

    `at` is the moment of the `StatusChanged` that narrates the move, so the
    end the row says and the end the account says are one instant: a duration
    measured between two clocks is a duration measuring the difference between
    them, and the database's `now()` is the moment its transaction began.

    Committing is the caller's. The event that narrates this transition is
    written on the same connection, and a commit here would put the transition
    beyond reach of the account before the account existed.
    """
    ends_the_incident = to_status.is_terminal()
    a_persons_endings = [status for status in IncidentStatus if status.is_a_persons_ending()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident "
            "   SET status = %s, ended_at = CASE WHEN %s THEN %s ELSE NULL END "
            " WHERE id = %s AND status <> ALL(%s)",
            (to_status, ends_the_incident, at, incident_id, a_persons_endings)
        )

        return cursor.rowcount == 1


def escalate_unless_ended(conn: psycopg.Connection, incident_id: str, *, at: datetime) -> bool:
    """Moves an incident whose walk stopped without finishing to `escalated`,
    stamping its end, and says whether it did.

    Never from an ending - a person's, as `transition` refuses, nor the walk's
    own. A walk that mitigated the incident and failed after it, in the
    write-up, stopped nowhere: escalating it would call a mitigated incident
    one a person must take over, and re-stamp when it ended. In the statement
    rather than a read before it, for the reason `transition` gives - and
    because a read that failed would leave a walk that did stop unescalated,
    reading as work in progress that nothing is going to pick up.

    Committing is the caller's, as `transition`'s is.
    """
    endings = [status for status in IncidentStatus if status.is_terminal()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident SET status = %s, ended_at = %s "
            " WHERE id = %s AND status <> ALL(%s)",
            (IncidentStatus.ESCALATED, at, incident_id, endings)
        )

        return cursor.rowcount == 1


def withdraw(conn: psycopg.Connection, incident_id: str, *, at: datetime) -> bool:
    """Withdraws an incident from Argus, and says whether it took effect.

    `at` is the moment of the `StatusChanged` that says so, as `transition`'s
    is.

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
            "UPDATE incident SET status = %s, ended_at = %s "
            " WHERE id = %s AND status = ANY(%s)",
            (IncidentStatus.WITHDRAWN, at, incident_id, withdrawable)
        )
        withdrawn = cursor.rowcount == 1

    return withdrawn


def resolve(conn: psycopg.Connection, incident_id: str, *, at: datetime) -> bool:
    """Records that a person reported the incident resolved, and says whether
    it took effect.

    `at` is the moment of the `StatusChanged` that says so, as `transition`'s
    is.

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

    Committing is the caller's, as `transition`'s is.
    """
    resolvable = [status for status in IncidentStatus if status.accepts_resolution()]

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE incident SET status = %s, ended_at = COALESCE(ended_at, %s) "
            " WHERE id = %s AND status = ANY(%s)",
            (IncidentStatus.RESOLVED, at, incident_id, resolvable)
        )
        resolved = cursor.rowcount == 1

    return resolved


def get_recent(conn: psycopg.Connection, shapes: Shapes = SHIPPED) -> list[Incident]:
    """Every incident that can be read, newest first.

    A history view opens on what just happened, so the ordering is the whole
    point of the name: oldest-first would put the incident somebody came looking
    for at the bottom of the page.

    One whose row cannot be read - or was written by a newer Argus - is passed
    over with a warning rather than failing the list: one bad row would
    otherwise take every incident there has ever been off the page.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_INCIDENT_COLUMNS} "
            "  FROM incident "
            "ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()

    recent = []

    for row in rows:
        read = _read(row, shapes)

        if isinstance(read, Unreadable):
            logger.warning("incident passed over: its row cannot be read", extra={
                ARGUS_INCIDENT_ID: str(row["id"]), "why": read.why, "newer": read.newer
            })
        else:
            recent.append(read)

    return recent


def get_current(conn: psycopg.Connection, shapes: Shapes = SHIPPED) -> Incident | None:
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

    Raises where the incident's row cannot be read, as `get` does.
    """
    terminal = [status for status in IncidentStatus if status.is_terminal()]

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_INCIDENT_COLUMNS} "
            "  FROM incident "
            "ORDER BY status = ANY(%s), created_at DESC "
            " LIMIT 1",
            (terminal,)
        )
        row = cursor.fetchone()

    return _an_incident(row, shapes) if row is not None else None


def get_open_by_rule_and_service(conn: psycopg.Connection,
                                 rule: str,
                                 service: str) -> IncidentStanding | None:
    """The newest unfinished incident `rule` opened for `service`, if any.

    What a rule firing again while Argus is still on its incident joins: the
    incident going on rather than a second one beside it. Finished incidents are
    not looked at - once one is over, the rule firing again is a new incident.
    Nor are other services': a rule watching several pages for each, and the
    service paged for is what an incident investigates.

    Where it stands, not the whole incident: the alert it holds is not read,
    so one whose alert cannot be read is still the incident a firing joins.
    """
    still_going = [status for status in IncidentStatus if not status.is_terminal()]

    with conn.cursor(row_factory=class_row(IncidentStanding)) as cursor:
        cursor.execute(
            f"SELECT {_STANDING_COLUMNS} "
            "  FROM incident "
            " WHERE alert_rule = %s "
            "   AND alert_service = %s "
            "   AND status = ANY(%s) "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (rule, service, still_going)
        )
        return cursor.fetchone()


def get_newest_by_names_and_service(conn: psycopg.Connection,
                                    kind: str,
                                    values: Iterable[str],
                                    service: str) -> IncidentStanding | None:
    """The newest incident for `service` holding any of these names of this
    kind, whatever its status, if any.

    What an alert arriving again is matched to: a reminder of a firing joins
    the incident that firing opened. Every status is looked at, because
    whether an ending lets a reminder join is the caller's to decide. The
    newest, because a firing reminded of after Argus opened a second incident
    for it is held by both, and the newer is the latest word about it. Only
    `service`'s, because one alert group spans every service its rule watches
    and an incident holds every firing its notification carried.

    Where it stands, not the whole incident, as `get_open_by_rule_and_service`
    answers.
    """
    with conn.cursor(row_factory=class_row(IncidentStanding)) as cursor:
        cursor.execute(
            f"SELECT {_STANDING_COLUMNS} "
            "  FROM incident "
            " WHERE alert_service = %s "
            "   AND id IN (SELECT incident_id FROM incident_reference "
            "               WHERE kind = %s AND value = ANY(%s)) "
            "ORDER BY created_at DESC "
            " LIMIT 1",
            (service, kind, list(values))
        )
        return cursor.fetchone()


def get(conn: psycopg.Connection,
        incident_id: str,
        shapes: Shapes = SHIPPED) -> Incident | None:
    """The incident, brought up to the shapes `shapes` are at.

    Raises `NewerShape` where its alert was written by a newer Argus, and the
    failure that stopped it where its alert cannot be read: one incident asked
    for by name is not passed over, and read in part it would be read wrong.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_INCIDENT_COLUMNS} "
            "  FROM incident "
            " WHERE id = %s",
            (incident_id,)
        )
        row = cursor.fetchone()

    return _an_incident(row, shapes) if row is not None else None


def _an_incident(row: dict[str, Any], shapes: Shapes) -> Incident:
    """The incident a row of `_INCIDENT_COLUMNS` holds, its alert brought up to
    date before it is read."""
    alert = up_to_date(ALERT, row["shape"], row["alert_payload"], shapes)

    return Incident(id=row["id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    ended_at=row["ended_at"],
                    alert=Alert.model_validate(alert),
                    trace_context=row["trace_context"])


def _read(row: dict[str, Any], shapes: Shapes) -> Incident | Unreadable:
    """The incident a row holds, or what stopped it being read.

    Any failure, not a list of them: bringing a row up runs steps written for
    whatever an older release stored, and what one of them raises over a row
    it was not written for is not known in advance.
    """
    try:
        return _an_incident(row, shapes)
    except Exception as failure:
        return Unreadable.of(failure)
