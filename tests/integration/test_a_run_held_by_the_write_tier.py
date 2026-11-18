"""A run held for a change by the write tier, as the tier holds it.

The hold itself is pinned against a real row in the runs repository's suite,
on a connection the suite opens as it believes the tier does. What only this
file can say is that the tier does: that the holds `main` serves with keep the
run from being taken back while a change is made, hold back nobody's account
while they do, refuse a second change for the run once the tier's own wait for
it is up, and let the run go once a held connection has sat idle past the
tier's own bound.
"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from datetime import timedelta
from typing import Any, Final

import psycopg
import pytest
from argus_testkit import Assertion, Kept, Scenario, all_of, calling
from core import DatabaseSettings, Fence, connect_from_env, get_settings, utc_now
from core.events import AgentInvoked
from core.models import Actor, Alert
from incident_record.repository import events, incidents, runs
from write_mcp_server.fencing import HoldForAChange, holds_in_the_database

# The first claim's lease is over before it begins, which is what lets the next
# claim take the run back; the next one's outlasts the test.
A_LEASE_ALREADY_OVER: Final = timedelta(seconds=-1)
A_GENEROUS_LEASE: Final = timedelta(minutes=5)

# Bigger than anything published here: what is asked is whether an event comes
# back, not how many fit in a batch.
A_GENEROUS_BATCH: Final = 100

DONT_CARE_ALERT: Final = Alert(service="io-shop", alert_name="HighErrorRate")
DONT_CARE_PAUSED_WORKER: Final = "worker-that-was-paused"
DONT_CARE_WORKER: Final = "worker-that-came-after"

# How long the tier is told a change waits for its run, kept short so the test
# does not sit out the tier's own; and how long the test waits for the change
# to be refused - far past that moment, so a tier that set no wait at all fails
# the test rather than hanging it.
A_MOMENT_FOR_A_CHANGE_TO_WAIT: Final = timedelta(milliseconds=500)
LONG_PAST_THAT_MOMENT: Final = A_MOMENT_FOR_A_CHANGE_TO_WAIT * 20

# How long the tier is told a held connection may sit idle, kept short so the
# test does not sit out the tier's own - and no shorter, because a connection
# is idle between being opened and taking its lock too. And how long the test
# waits for the next hold: past that moment, and past the tier's own wait for a
# run, so a hold never let go is refused as one in flight rather than left
# waiting.
A_MOMENT_TO_SIT_IDLE: Final = timedelta(milliseconds=500)
LONG_PAST_SITTING_IDLE: Final = A_MOMENT_TO_SIT_IDLE * 20


@pytest.mark.integration
def test_an_event_published_while_the_tier_holds_a_run_for_a_change_is_delivered() -> None:
    # A restart takes minutes, and the tier holds its run for all of them.
    # Every incident's account is read by one relay, so a hold that kept a
    # transaction in flight would stop all of them at once.
    with (
        connect_from_env() as conn,
        holds_in_the_database(DatabaseSettings.of(get_settings())) as hold_for_a_change,
        ExitStack() as the_change
    ):
        Scenario() \
            .given(
                incident_id := incidents.create(conn, DONT_CARE_ALERT, at=utc_now()),
                held := _a_claim_on_a_run_for(conn, incident_id, A_GENEROUS_LEASE),
                the_start_of_the_log := _the_end_of_the_log(conn),
                still_held := the_change.enter_context(hold_for_a_change(held)),
                some_event := AgentInvoked(incident_id=incident_id, agent=Actor.MITIGATION),
                calling(lambda: _published(conn, some_event))
            ) \
            .when(
                lambda: events.get_since(conn, the_start_of_the_log, A_GENEROUS_BATCH)
            ) \
            .then(all_of(
                _the_hold_was_had(still_held),
                _the_batch_reads([some_event.kind])
            ))


@pytest.mark.integration
@pytest.mark.parametrize("change", ["being-made", "done"])
def test_a_run_the_tier_holds_for_a_change_is_not_taken_back_until_the_change_is_done(
    change: str
) -> None:
    # Its lease is over, so any worker looking would take it - and the next
    # claim would walk on while a change made for the last one is still landing.
    with (
        connect_from_env() as conn,
        holds_in_the_database(DatabaseSettings.of(get_settings())) as hold_for_a_change,
        ExitStack() as the_change
    ):
        Scenario() \
            .given(
                incident_id := incidents.create(conn, DONT_CARE_ALERT, at=utc_now()),
                held := _a_claim_on_a_run_for(conn, incident_id, A_LEASE_ALREADY_OVER),
                calling(lambda: the_change.enter_context(hold_for_a_change(held))),
                calling(the_change.close if change == "done" else lambda: None)
            ) \
            .when(
                lambda: runs.claim(conn, DONT_CARE_WORKER, A_GENEROUS_LEASE)
            ) \
            .then(
                _taken_back(change == "done")
            )


@pytest.mark.integration
def test_a_second_change_for_a_run_the_tier_holds_is_refused_once_the_tiers_wait_is_up(
) -> None:
    # The same change asked again, over a connection that gave out while the
    # first was still being made. The tier sets how long it waits for the run,
    # so the second is refused rather than made twice once the wait is up - and
    # rather than waiting for as long as the first change takes.
    with (
        connect_from_env() as conn,
        holds_in_the_database(
            DatabaseSettings.of(get_settings()),
            wait=_said_as_postgres_says_it(A_MOMENT_FOR_A_CHANGE_TO_WAIT)
        ) as hold_for_a_change,
        ExitStack() as the_change
    ):
        Scenario() \
            .given(
                incident_id := incidents.create(conn, DONT_CARE_ALERT, at=utc_now()),
                held := _a_claim_on_a_run_for(conn, incident_id, A_GENEROUS_LEASE),
                still_held := the_change.enter_context(hold_for_a_change(held))
            ) \
            .when(
                lambda: _a_second_hold_entered(hold_for_a_change, held, LONG_PAST_THAT_MOMENT)
            ) \
            .then(all_of(
                _the_hold_was_had(still_held),
                _refused_as_a_change_in_flight()
            ))


@pytest.mark.integration
def test_a_run_held_on_a_connection_gone_idle_past_the_tiers_bound_is_let_go() -> None:
    # A tier that hung holding a run - wedged in a change, or gone without
    # closing its connection - would keep every change for the run refused for
    # as long as it hung. The tier bounds how long a held connection may say
    # nothing, and past it the database closes the connection and the run goes
    # with it. Letting go of the first hold then fails, on a connection already
    # closed - asserted as the case's last word rather than left to the way out,
    # where it would replace whatever failure the case had to report.
    with (
        connect_from_env() as conn,
        holds_in_the_database(
            DatabaseSettings.of(get_settings()),
            idle=_said_as_postgres_says_it(A_MOMENT_TO_SIT_IDLE)
        ) as hold_for_a_change,
        ExitStack() as the_change
    ):
        Scenario() \
            .given(
                incident_id := incidents.create(conn, DONT_CARE_ALERT, at=utc_now()),
                held := _a_claim_on_a_run_for(conn, incident_id, A_GENEROUS_LEASE),
                still_held := the_change.enter_context(hold_for_a_change(held))
            ) \
            .when(
                lambda: _a_second_hold_entered(hold_for_a_change, held, LONG_PAST_SITTING_IDLE)
            ) \
            .then(all_of(
                _the_hold_was_had(still_held),
                _the_second_hold_said_held(),
                _letting_go_of_the_first_hold_fails(the_change)
            ))


def _said_as_postgres_says_it(wait: timedelta) -> str:
    """A duration as a Postgres setting takes it, in milliseconds."""
    return f"{int(wait.total_seconds() * 1000)}ms"


def _a_second_hold_entered(hold_for_a_change: HoldForAChange,
                           held: Fence,
                           waiting_at_most: timedelta) -> object:
    """A second hold for `held`, entered on a thread of its own - what it said or
    raised, or that it was still waiting once `waiting_at_most` was up."""
    answered: Kept[object] = Kept()

    def hold() -> None:
        try:
            with hold_for_a_change(held) as still_held:
                answered.take(still_held)
        except Exception as refused:
            answered.take(refused)

    second = threading.Thread(target=hold, daemon=True)
    second.start()
    second.join(waiting_at_most.total_seconds())

    return answered.only() if answered.taken else "nothing - it was still waiting"


def _refused_as_a_change_in_flight() -> Assertion[Any]:
    def assertion(answered: Any) -> bool:
        if not isinstance(answered, runs.ChangeInFlight):
            raise AssertionError(
                f"Expected the second change refused as one already in flight, got "
                f"[{answered!r}]."
            )

        return True

    return assertion


def _the_second_hold_said_held() -> Assertion[Any]:
    def assertion(answered: Any) -> bool:
        if answered is not True:
            raise AssertionError(
                f"Expected the second hold to say the run was held once the first's "
                f"connection had gone idle past the tier's bound, got [{answered!r}]."
            )

        return True

    return assertion


def _letting_go_of_the_first_hold_fails(the_change: ExitStack) -> Assertion[Any]:
    """The first hold let go, on a connection the database has closed - which
    fails, and is expected to. Let go here rather than as the case unwinds, so
    that failure is asserted and the stack is empty by the way out."""
    def assertion(_answered: Any) -> bool:
        try:
            the_change.close()
        except psycopg.OperationalError:
            return True
        except Exception as other:
            raise AssertionError(
                f"Expected letting go of the first hold to fail on its closed connection, "
                f"got [{type(other).__name__}: {other}]."
            ) from other

        raise AssertionError(
            "Expected letting go of the first hold to fail on its closed connection, and "
            "it was let go."
        )

    return assertion


def _a_claim_on_a_run_for(conn: psycopg.Connection,
                          incident_id: str,
                          lease: timedelta) -> Fence:
    """The claim a worker holds on a run for the incident, for `lease`, as a call
    to the write tier names it - committed, as a worker commits its claim."""
    runs.enqueue(conn, incident_id)
    claimed = runs.claim(conn, DONT_CARE_PAUSED_WORKER, lease)
    assert claimed is not None
    conn.commit()

    return Fence(run_id=claimed.id, epoch=claimed.epoch)


def _the_end_of_the_log(conn: psycopg.Connection) -> int:
    """Where the log ends now, asked in SQL of its own rather than of the reader
    under test."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT coalesce(max(seq), 0) FROM incident_event")
        row = cursor.fetchone()
        assert row is not None

        return int(row[0])


def _published(conn: psycopg.Connection, event: AgentInvoked) -> None:
    """An event published and landed, as every publisher lands it."""
    events.record(conn, event)
    conn.commit()


def _the_hold_was_had(still_held: bool) -> Assertion[Any]:
    """The hold the case starts from was had - without it nothing was held, and
    whatever the case asks next says nothing about a hold."""
    def assertion(_answered: Any) -> bool:
        if still_held is not True:
            raise AssertionError(
                f"Expected the hold to say the run was held, and it said [{still_held}]."
            )

        return True

    return assertion


def _the_batch_reads(expected: list[str]) -> Assertion[list[events.RecordedEvent]]:
    def assertion(delivered: list[events.RecordedEvent]) -> bool:
        kinds = [entry.event.kind for entry in delivered]

        if kinds != expected:
            raise AssertionError(f"Expected the kinds {expected}, got {kinds}.")

        return True

    return assertion


def _taken_back(expected: bool) -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if (claimed is not None) is not expected:
            raise AssertionError(
                f"Expected the run {"taken back once the change was done" if expected
                                    else "left alone while the change was being made"}, "
                f"and it was claimed by [{claimed.claimed_by if claimed else None}]."
            )

        return True

    return assertion
