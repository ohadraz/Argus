from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import incidents, runs

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

# Long enough that nothing in this test expires on its own: what is being
# measured here is who gets the run, not what happens when a holder goes quiet.
A_GENEROUS_LEASE = timedelta(minutes=5)

# Short enough to have expired by the time it is tested against, without the
# test waiting for it: a lease already in the past is the state a worker that
# stopped mid-walk leaves behind, and it is arranged rather than waited for.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)


@pytest.mark.integration
def test_a_queued_run_is_claimed_by_one_worker_and_not_by_a_second() -> None:
    # Two workers at once is not the demo's shape, but a restart overlapping
    # its predecessor is - and an incident walked twice spends two mitigations
    # on one fault. The claim is what makes the second worker harmless, so it
    # is asserted from two connections rather than reasoned about from one.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    one_worker = "worker-that-got-there-first"
    another_worker = "worker-that-came-second"

    with (
        psycopg.connect(DATABASE_URL) as conn,
        psycopg.connect(DATABASE_URL) as another_conn,
    ):
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                incident_id := an_enqueued_run_for(some_alert)
            ) \
            .when(
                (
                    runs.claim(conn, one_worker, A_GENEROUS_LEASE),
                    runs.claim(another_conn, another_worker, A_GENEROUS_LEASE),
                )
            ) \
            .then(all_of(
                _exactly_one_worker_claimed_it(),
                _the_claimed_run_is_for(incident_id),
            ))


@pytest.mark.integration
def test_a_run_whose_lease_ran_out_is_taken_up_again() -> None:
    # The worker that took this run is gone - killed, restarted, redeployed -
    # and nothing said so. The lease is what says so, and without it a single
    # crash parks an incident mid-investigation forever.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_that_stopped = "worker-that-was-killed-mid-walk"
    the_worker_that_came_after = "worker-that-started-next"

    with psycopg.connect(DATABASE_URL) as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                incident_id := an_enqueued_run_for(dont_care_alert),
                runs.claim(conn, the_worker_that_stopped, A_LEASE_ALREADY_OVER)
            ) \
            .when(
                runs.claim(conn, the_worker_that_came_after, A_GENEROUS_LEASE)
            ) \
            .then(all_of(
                _a_run_was_claimed(),
                _the_run_is_for(incident_id),
                _the_run_is_held_by(the_worker_that_came_after),
            ))


@pytest.mark.integration
def test_a_run_still_being_walked_is_not_taken_from_its_worker() -> None:
    # The other half of the same rule, and the half that costs something when
    # it is wrong: an investigation legitimately takes minutes, and a run
    # reclaimed while its worker is still walking it is the duplicate walk the
    # claim exists to prevent.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    the_worker_still_walking_it = "worker-that-is-still-working"
    dont_care_worker = "worker-looking-for-something-to-do"

    with psycopg.connect(DATABASE_URL) as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                an_enqueued_run_for(dont_care_alert),
                runs.claim(conn, the_worker_still_walking_it, A_GENEROUS_LEASE)
            ) \
            .when(
                runs.claim(conn, dont_care_worker, A_GENEROUS_LEASE)
            ) \
            .then(
                _nothing_was_claimed()
            )


def _a_run_was_claimed() -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed is None:
            raise AssertionError(
                "Expected the run to be claimable once its lease had run out, "
                "but nothing was claimed."
            )

        return True

    return assertion


def _nothing_was_claimed() -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed is not None:
            raise AssertionError(
                f"Expected no run to be claimable while its worker is still "
                f"walking it, but run [{claimed.id}] was taken from "
                f"[{claimed.claimed_by}]."
            )

        return True

    return assertion


def _the_run_is_for(incident_id: str) -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed.incident_id != incident_id:
            raise AssertionError(
                f"Expected the reclaimed run to be for incident "
                f"[{incident_id}], got [{claimed.incident_id}]."
            )

        return True

    return assertion


def _the_run_is_held_by(worker: str) -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed.claimed_by != worker:
            raise AssertionError(
                f"Expected the reclaimed run to be held by [{worker}], got "
                f"[{claimed.claimed_by}]."
            )

        return True

    return assertion


def _an_enqueued_run_for(conn: psycopg.Connection, alert: Alert) -> str:
    """An incident with a run waiting to be walked - the state the webhook
    leaves behind, and the only state a worker has anything to do in."""
    incident_id = incidents.create(conn, alert)
    runs.enqueue(conn, incident_id)

    return incident_id


def _exactly_one_worker_claimed_it() -> Assertion[Any]:
    def assertion(claims: Any) -> bool:
        claimed = [claim for claim in claims if claim is not None]

        if len(claimed) != 1:
            raise AssertionError(
                f"Expected exactly 1 of the 2 workers to claim the run, got "
                f"{len(claimed)}."
            )

        return True

    return assertion


def _the_claimed_run_is_for(incident_id: str) -> Assertion[Any]:
    def assertion(claims: Any) -> bool:
        claimed = next(claim for claim in claims if claim is not None)

        if claimed.incident_id != incident_id:
            raise AssertionError(
                f"Expected the claimed run to be for incident [{incident_id}], "
                f"got [{claimed.incident_id}]."
            )

        return True

    return assertion
