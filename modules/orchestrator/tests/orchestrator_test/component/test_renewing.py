from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import psycopg
import pytest
from argus_core import Connections, connect_from_env, in_real_time, utc_now
from argus_core.models import Alert
from argus_incidents.repository import incidents, runs
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged
from orchestrator.renewing import Stopped, keep_renewing

# Where renewing logs from.
THE_RENEWER = "orchestrator.renewing"

# Over before it is renewed, so only a renewal keeps the run its holder's.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)

# Long enough that nothing here runs out on its own.
A_GENEROUS_LEASE = timedelta(minutes=5)

# How many rounds `stopped` allows before saying stop, where the count is not
# what the test is about.
SOME_ROUNDS = 5


@pytest.mark.component
def test_a_held_run_is_renewed_every_third_of_its_lease_until_told_to_stop(
    a_clean_database: None
) -> None:
    # Every round renews, and every wait between them is a third of the lease -
    # so two may be missed before anything else may take the run.
    asked: list[float] = []
    opened: list[None] = []
    some_rounds = 3

    with connect_from_env() as conn:
        Scenario() \
            .given(
                held := _a_run_claimed_with(conn, A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: keep_renewing(held, A_GENEROUS_LEASE,
                                      _connections_counting_into(opened),
                                      _stopped_after(some_rounds, asked))
            ) \
            .then(all_of(
                _renewed_times(opened, some_rounds),
                _each_wait_was_a_third_of(A_GENEROUS_LEASE, asked),
                _the_run_is_still_held(conn, held)
            ))


@pytest.mark.component
def test_a_renewal_that_failed_is_followed_by_the_next(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Stopping at the first failed renewal let one database blip end renewing
    # for good: the lease ran out under a walk still going, and the run was
    # taken back and walked twice at once.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                held := _a_run_claimed_with(conn, A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: keep_renewing(held, A_GENEROUS_LEASE,
                                      _connections_failing_the_first_time(),
                                      _stopped_after(2, []))
            ) \
            .then(all_of(
                _the_run_is_still_held(conn, held),
                one_record_was_logged(caplog, THE_RENEWER, logging.WARNING,
                                      "claim could not be renewed, renewing again next time",
                                      values={"run_id": held.id}, failure=ConnectionError)
            ))


@pytest.mark.component
def test_renewing_stops_once_the_run_is_no_longer_held(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The run was taken back while its holder was paused. Renewing on would
    # keep asking for a run that is somebody else's.
    opened: list[None] = []

    with connect_from_env() as conn:
        Scenario() \
            .given(
                the_lost_claim := _a_run_claimed_with(conn, A_LEASE_ALREADY_OVER),
                _the_run_taken_back(conn)
            ) \
            .when(
                lambda: keep_renewing(the_lost_claim, A_GENEROUS_LEASE,
                                      _connections_counting_into(opened),
                                      _stopped_after(SOME_ROUNDS, []))
            ) \
            .then(all_of(
                _renewed_times(opened, 1),
                one_record_was_logged(caplog, THE_RENEWER, logging.WARNING,
                                      "run no longer held by this claim, renewing stopped",
                                      values={"run_id": the_lost_claim.id,
                                              "epoch": the_lost_claim.epoch})
            ))


def _a_run_claimed_with(conn: psycopg.Connection, lease: timedelta) -> runs.Run:
    """An incident's run, claimed for `lease`."""
    incident_id = incidents.create(conn, Alert(service="kuki-service",
                                               alert_name="HighErrorRate"), at=utc_now())
    runs.enqueue(conn, incident_id)
    claimed = runs.claim(conn, "worker-holding-it", lease)
    assert claimed is not None

    return claimed


def _the_run_taken_back(conn: psycopg.Connection) -> runs.Run:
    """The run claimed again by another worker, its lease having run out."""
    claimed = runs.claim(conn, "worker-that-came-after", A_GENEROUS_LEASE)
    assert claimed is not None

    return claimed


def _stopped_after(rounds: int, asked: list[float]) -> Stopped:
    """Says carry on `rounds` times and then stop, keeping each wait it was
    asked for and waiting none of it."""
    def stopped(seconds: float) -> bool:
        asked.append(seconds)

        return len(asked) > rounds

    return stopped


def _connections_counting_into(opened: list[None]) -> Connections:
    """Real connections, each one opened kept count of - a renewal is one."""
    @contextmanager
    def counted() -> Iterator[psycopg.Connection]:
        opened.append(None)

        with connect_from_env() as conn:
            yield conn

    return counted


def _connections_failing_the_first_time() -> Connections:
    """A database unreachable for the first renewal, and reachable after."""
    attempts: list[None] = []

    @contextmanager
    def failing_once() -> Iterator[psycopg.Connection]:
        attempts.append(None)

        if len(attempts) == 1:
            raise ConnectionError("the database could not be reached")

        with connect_from_env() as conn:
            yield conn

    return failing_once


def _renewed_times(opened: list[None], expected: int) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        if len(opened) != expected:
            raise AssertionError(f"Expected {expected} renewals, got {len(opened)}.")

        return True

    return assertion


def _each_wait_was_a_third_of(lease: timedelta, asked: list[float]) -> Assertion[None]:
    expected = in_real_time(lease.total_seconds() / 3)

    def assertion(_result: None) -> bool:
        if any(seconds != expected for seconds in asked):
            raise AssertionError(
                f"Expected every wait between renewals to be a third of the lease, "
                f"[{expected}] seconds, got {asked}."
            )

        return True

    return assertion


def _the_run_is_still_held(conn: psycopg.Connection, held: runs.Run) -> Assertion[None]:
    """That nobody else can take the run - asserted as what another worker
    gets, not as the lease's timestamp."""
    def assertion(_result: None) -> bool:
        claimed = runs.claim(conn, "worker-looking-for-something-to-do", A_GENEROUS_LEASE)

        if claimed is not None:
            raise AssertionError(
                f"Expected run [{held.id}] to stay its holder's, and "
                f"[{claimed.claimed_by}] took it."
            )

        return True

    return assertion
