from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest
from argus_core.config import get_settings
from argus_core.db import connect
from orchestrator.repository import incidents
from orchestrator.repository.runs import RunState
from psycopg import sql

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    INVESTIGATION_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
)
from tests.e2e.framework.flags import (
    only_the_boot_flags_were_left_in_the_provider,
    the_boot_flags_were_put_back,
    the_flag_provider_forgot_every_change,
)

# The one table that is not the suite's to empty. The rates are fetched from
# outside and cached here, and they do not change between cases - a teardown
# that dropped them would send the next case back out to the source for the
# same figures.
_KEPT_TABLES = ("exchange_rate",)

# How long a withdrawn walk may still take to stop.
#
# Withdrawal is asked before a node runs, so the wait is one node's worth: the
# node already in flight when the button was pressed runs to its own end.
# Mitigation's verification is the longest of those by the clock, but it asks
# the question inside its own wait and stops within a poll of it - which leaves
# an investigation as the longest thing that cannot be interrupted, and the
# framework already derives that bound from the settings.
#
# Derived rather than chosen, so the day a setting moves this moves with it.
# Nothing is expected to come near it: under replay a withdrawn walk stops in
# under a second, and reaching this bound is what a wedged stack looks like.
_SETTLING_TIMEOUT_SECONDS = max(
    INVESTIGATION_TIMEOUT_SECONDS,
    get_settings().mitigation_verification_timeout_seconds
)
_SETTLING_POLL_SECONDS = 0.5


@pytest.fixture(autouse=True)
def a_world_each_case_leaves_as_it_found_it() -> Iterator[None]:
    """Puts Argus and the Target Environment back the way the stack starts them.

    Every case, not only the ones that obviously dirty something. Argus now
    changes the world it investigates - it turns flags off, turns them on, and
    puts them back when a mitigation is refuted - so the state a case ends in
    is rarely the state it arranged, and rarely something the case itself can
    predict.

    A case ends when its own assertion holds, not when the walk does: the
    webhook answers as soon as the run is queued, so the walk a case started is
    usually still running while this executes. That is what the first three
    steps are about, and why they come before everything else:

    - every incident still live is withdrawn, through the same door a human
      would press. Nothing here waits for a walk to finish of its own accord,
      because a walk left running would seed itself from the next case's
      recordings and write rows the next case would read as its own;
    - the runs are then waited out. Withdrawal only marks - the walk finds out
      by reading the incident back and unwinds what it changed itself - so the
      moment the mark lands is not the moment the writing stops. Waiting is
      what lets everything below assume it is the only writer;
    - every table is emptied, `exchange_rate` excepted. What to empty is asked
      of the database rather than listed here: a list would be a second
      statement of the schema, and the day a table is added the suite would
      keep passing while quietly leaking its rows into the next case.

    Then the Target Environment, which is a state a fresh stack boots into
    rather than a quiet one: the shop's feature flag off, the kill switch on,
    and nothing recorded as having been switched. Four things are undone, and
    the order is the point:

    - the Target Service's scenario is reset, which ends whatever condition it
      was staging and has the last word on the flags it owns;
    - both boot flags are put back where the stack starts them. Healthy is not
      the same state for the two of them, so this restores each to its own -
      switching everything off would leave the kill switch withdrawn and the
      shop failing for a reason nothing in the history explains;
    - every flag the environment did not boot with is deleted. The provider is
      shared with the demo, and a flag a case brought into existence is one
      somebody would have to explain in front of an audience;
    - the provider's record of which flags changed is erased. This is the one
      that would otherwise couple the cases to their order: a flag toggled in
      one case is evidence in the next, whatever state the flag itself was left
      in. It goes last because every step above is itself a change the provider
      records.

    Teardown rather than setup, so a failing case leaves nothing behind for a
    human to clear before rerunning.
    """
    yield

    _every_live_incident_was_withdrawn()
    _every_run_came_to_a_stop()
    _every_table_was_emptied()
    _the_target_service_scenario_was_reset()

    the_boot_flags_were_put_back()
    only_the_boot_flags_were_left_in_the_provider()
    the_flag_provider_forgot_every_change()


def _every_live_incident_was_withdrawn() -> None:
    """Takes back whatever Argus is still working on, at the human's own door.

    Over HTTP rather than by calling the Orchestrator in-process: the walk to
    be stopped is running in the worker, and the endpoint is the seam that was
    built for somebody outside it to press.

    A refusal is not checked, and deliberately: the only way this asks to
    withdraw an incident that cannot be is that the walk ended between the read
    and the call, which is the outcome being asked for anyway.
    """
    with connect() as conn:
        live = [
            incident
            for incident in incidents.get_recent(conn)
            if not incident.status.is_terminal()
        ]

    for incident in live:
        httpx.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident.id}/withdraw",
            timeout=REQUEST_TIMEOUT_SECONDS
        )


def _every_run_came_to_a_stop() -> None:
    """Waits until nothing is walking, and says so loudly if something still is.

    Loudly because the alternative is worse than a slow suite: a table emptied
    under a running walk is a table the walk fills back in, and the case that
    then fails is the next one, on evidence it never arranged.
    """
    deadline = time.monotonic() + _SETTLING_TIMEOUT_SECONDS

    while True:
        still_going = _the_runs_still_going()

        if not still_going:
            return

        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Every incident was withdrawn, and [{len(still_going)}] run(s) "
                f"were still going [{_SETTLING_TIMEOUT_SECONDS}s] later: "
                f"{still_going}. The next case would have run against a walk "
                f"that is still writing."
            )

        time.sleep(_SETTLING_POLL_SECONDS)


def _the_runs_still_going() -> list[str]:
    """The runs a worker is walking or is about to, by id.

    Queued counts as going: a queued run is one a worker is free to claim at
    any moment, and one claimed after the tables were emptied would walk an
    incident that no longer exists.
    """
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM incident_run WHERE state = ANY(%s)",
            ([RunState.QUEUED, RunState.RUNNING],)
        )

        return [str(run_id) for (run_id,) in cursor.fetchall()]


def _every_table_was_emptied() -> None:
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [
            name for (name,) in cursor.fetchall() if name not in _KEPT_TABLES
        ]

        if tables:
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                )
            )

        conn.commit()


def _the_target_service_scenario_was_reset() -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=REQUEST_TIMEOUT_SECONDS
    )
