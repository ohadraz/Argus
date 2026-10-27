from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core import Fence, connect_from_env, fence, utc_now, was_lost
from argus_core.models import Alert
from argus_incidents.repository import incidents, runs
from argus_testkit import Assertion, Scenario, all_of, attempting, calling

from argus_incidents_test.framework import no_column_is_empty

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
        connect_from_env() as conn,
        connect_from_env() as another_conn
    ):
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                incident_id := an_enqueued_run_for(some_alert)
            ) \
            .when(
                lambda: (
                    runs.claim(conn, one_worker, A_GENEROUS_LEASE),
                    runs.claim(another_conn, another_worker, A_GENEROUS_LEASE)
                )
            ) \
            .then(all_of(
                _exactly_one_worker_claimed_it(),
                _the_claimed_run_is_for(incident_id)
            ))


@pytest.mark.integration
def test_a_run_whose_lease_ran_out_is_taken_up_again() -> None:
    # The worker that took this run is gone - killed, restarted, redeployed -
    # and nothing said so. The lease is what says so, and without it a single
    # crash parks an incident mid-investigation forever.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_that_stopped = "worker-that-was-killed-mid-walk"
    the_worker_that_came_after = "worker-that-started-next"

    with connect_from_env() as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                incident_id := an_enqueued_run_for(dont_care_alert),
                calling(lambda: runs.claim(conn, the_worker_that_stopped, A_LEASE_ALREADY_OVER))
            ) \
            .when(
                lambda: runs.claim(conn, the_worker_that_came_after, A_GENEROUS_LEASE)
            ) \
            .then(all_of(
                _a_run_was_claimed(),
                _the_run_is_for(incident_id),
                _the_run_is_held_by(the_worker_that_came_after)
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

    with connect_from_env() as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                an_enqueued_run_for(dont_care_alert),
                calling(lambda: runs.claim(conn, the_worker_still_walking_it, A_GENEROUS_LEASE))
            ) \
            .when(
                lambda: runs.claim(conn, dont_care_worker, A_GENEROUS_LEASE)
            ) \
            .then(
                _nothing_was_claimed()
            )


@pytest.mark.integration
def test_only_runs_waiting_or_being_walked_are_unsettled() -> None:
    # Asked by whoever is about to change what a walk acts on: whether any walk
    # is still live. A run waiting to be taken is as live as one being walked -
    # a worker takes it the moment one is free - and a run that finished or
    # failed acts on nothing again.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    dont_care_reason = "the walk ran out of tool calls"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                a_finished_run := _a_claimed_run_for(conn, dont_care_alert),
                a_failed_run := _a_claimed_run_for(conn, dont_care_alert),
                a_run_being_walked := _a_claimed_run_for(conn, dont_care_alert),
                a_waiting_incident_id := _an_enqueued_run_for(conn, dont_care_alert),
                calling(lambda: runs.finish(conn, a_finished_run)),
                calling(lambda: runs.fail(conn, a_failed_run, dont_care_reason))
            ) \
            .when(
                lambda: runs.get_unsettled_runs(conn)
            ) \
            .then(
                _the_runs_are_for({a_run_being_walked.incident_id, a_waiting_incident_id})
            )


@pytest.mark.integration
def test_a_run_taken_back_is_held_under_a_later_epoch_than_the_claim_it_replaced() -> None:
    # A lease says when a holder may be presumed gone, and cannot stop one that
    # was only paused from carrying on once it wakes. The epoch is what tells
    # that holder the run is no longer its own.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                the_paused_claim := _a_claim_by(conn, "worker-that-was-paused",
                                                A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: runs.claim(conn, "worker-that-came-after", A_GENEROUS_LEASE)
            ) \
            .then(
                _a_later_epoch_than(the_paused_claim)
            )


@pytest.mark.integration
def test_a_renewal_by_the_claim_holding_the_run_keeps_it_and_says_so() -> None:
    # Claimed with a lease already over, so only the renewal stands between the
    # run and the next worker looking for something to do.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                held := _a_claim_by(conn, "worker-still-walking-it", A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: (runs.renew(conn, held, A_GENEROUS_LEASE),
                         runs.claim(conn, "worker-looking-for-something-to-do",
                                    A_GENEROUS_LEASE))
            ) \
            .then(all_of(
                _the_renewal_said_the_run_is_still_held(),
                _nobody_else_took_it()
            ))


@pytest.mark.integration
def test_a_renewal_by_a_claim_since_taken_back_extends_nothing_and_says_so() -> None:
    # The holder that was paused wakes and renews. Extending the lease there
    # would keep the new holder's run from being taken back when that holder
    # stops - and the old one has nothing left to keep alive.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                the_lost_claim := _a_claim_by(conn, "worker-that-was-paused",
                                              A_LEASE_ALREADY_OVER),
                the_new_claim := _a_claim_by(conn, "worker-that-came-after",
                                             A_GENEROUS_LEASE)
            ) \
            .when(
                lambda: runs.renew(conn, the_lost_claim, A_GENEROUS_LEASE)
            ) \
            .then(all_of(
                _it_says_the_run_is_no_longer_held(),
                _the_lease_is_as_its_holder_left_it(conn, the_new_claim)
            ))


@pytest.mark.integration
def test_a_renewal_of_a_settled_run_extends_nothing_and_says_so() -> None:
    # A settled run is nobody's; a lease put back on it would read as a walk
    # still in progress.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                settled := _a_claimed_run_for(conn, dont_care_alert),
                calling(lambda: runs.finish(conn, settled))
            ) \
            .when(
                lambda: runs.renew(conn, settled, A_GENEROUS_LEASE)
            ) \
            .then(all_of(
                _it_says_the_run_is_no_longer_held(),
                _the_run_has_no_lease(conn, settled.id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("settling", ["finish", "fail"])
def test_a_run_settled_by_the_claim_holding_it_is_settled_and_says_so(settling: str) -> None:
    # Claimed with a lease already over and taken up by nobody since: still
    # this claim's to settle, because the epoch says who holds a run and the
    # lease only when somebody else may take it. Refused here, the run would be
    # logged as lost, taken back once its lease was noticed, and walked again.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_reason = "the walk ran out of tool calls"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                held := _a_claim_by(conn, "worker-whose-lease-ran-out", A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: (runs.finish(conn, held) if settling == "finish"
                         else runs.fail(conn, held, some_reason))
            ) \
            .then(all_of(
                _it_says_the_run_was_settled(),
                _the_run_is_settled_as(conn, held.id,
                                       runs.RunState.DONE if settling == "finish"
                                       else runs.RunState.FAILED,
                                       None if settling == "finish" else some_reason)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("settling", ["finish", "fail"])
def test_a_run_taken_back_is_not_settled_by_the_claim_it_replaced(settling: str) -> None:
    # The paused holder wakes and settles. Settling there would end a run
    # another worker is walking, and nothing would ever walk it again.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_reason = "the walk ran out of tool calls"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                the_lost_claim := _a_claim_by(conn, "worker-that-was-paused",
                                              A_LEASE_ALREADY_OVER),
                the_new_claim := _a_claim_by(conn, "worker-that-came-after",
                                             A_GENEROUS_LEASE)
            ) \
            .when(
                lambda: (runs.finish(conn, the_lost_claim) if settling == "finish"
                         else runs.fail(conn, the_lost_claim, dont_care_reason))
            ) \
            .then(all_of(
                _it_says_the_run_was_not_settled(),
                _the_run_is_as_its_holder_left_it(conn, the_new_claim)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("settling", ["finish", "fail"])
def test_settling_a_run_leaves_committing_it_to_the_caller(settling: str) -> None:
    # A failed run's claims, its escalation and its failure are one moment, and
    # the caller is the one holding all three.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_reason = "the walk ran out of tool calls"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                held := _a_claimed_run_for(conn, dont_care_alert),
                calling(lambda: runs.finish(conn, held) if settling == "finish"
                        else runs.fail(conn, held, dont_care_reason)),
                calling(conn.rollback)
            ) \
            .when(
                lambda: runs.get(conn, held.id)
            ) \
            .then(
                _the_run_is_still_running()
            )


@pytest.mark.integration
def test_a_run_is_not_taken_back_while_a_write_for_its_claim_is_still_open() -> None:
    # The holder's lease is over, but a write it made for the run has not ended.
    # Taking the run back now would let that write land under the new holder's
    # walk, so the claim passes the run over rather than waiting on it.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with (
        connect_from_env() as conn,
        connect_from_env() as the_holders_conn
    ):
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                held := _a_claim_by(conn, "worker-that-was-paused", A_LEASE_ALREADY_OVER),
                calling(lambda: _a_write_left_open_for(the_holders_conn, held))
            ) \
            .when(
                lambda: runs.claim(conn, "worker-looking-for-something-to-do", A_GENEROUS_LEASE)
            ) \
            .then(
                _nothing_was_taken_back()
            )

        the_holders_conn.rollback()


@pytest.mark.integration
def test_a_run_taken_back_once_its_claims_write_ended_refuses_that_claims_next_one() -> None:
    # The write ended, the run was taken back, and the paused holder writes
    # again: refused, and told as the lost run it is.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with (
        connect_from_env() as conn,
        connect_from_env() as the_holders_conn
    ):
        Scenario() \
            .given(
                _an_enqueued_run_for(conn, dont_care_alert),
                held := _a_claim_by(conn, "worker-that-was-paused", A_LEASE_ALREADY_OVER),
                calling(lambda: _a_write_left_open_for(the_holders_conn, held)),
                calling(the_holders_conn.commit)
            ) \
            .when(
                lambda: (runs.claim(conn, "worker-that-came-after", A_GENEROUS_LEASE),
                         attempting(lambda: _a_write_on(the_holders_conn, held))())
            ) \
            .then(all_of(
                _it_was_taken_back_by("worker-that-came-after"),
                _the_next_write_was_refused_as_a_lost_run()
            ))

        the_holders_conn.rollback()


def _a_write_left_open_for(conn: psycopg.Connection, held: runs.Run) -> None:
    """A write the holder makes for its claim, its transaction not yet ended."""
    fence(conn, Fence(run_id=held.id, epoch=held.epoch))
    _a_write_on(conn, held)


def _a_write_on(conn: psycopg.Connection, held: runs.Run) -> None:
    conn.execute("UPDATE incident SET status = status WHERE id = %s", (held.incident_id,))


def _nothing_was_taken_back() -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed is not None:
            raise AssertionError(
                f"Expected the run passed over while a write for its claim was open, and "
                f"[{claimed.claimed_by}] took it."
            )

        return True

    return assertion


def _it_was_taken_back_by(worker: str) -> Assertion[Any]:
    def assertion(claimed_then_refused: Any) -> bool:
        claimed, _ = claimed_then_refused

        if claimed is None or claimed.claimed_by != worker:
            raise AssertionError(
                f"Expected the run taken back by [{worker}] once the write had ended, got "
                f"[{None if claimed is None else claimed.claimed_by}]."
            )

        return True

    return assertion


def _the_next_write_was_refused_as_a_lost_run() -> Assertion[Any]:
    def assertion(claimed_then_refused: Any) -> bool:
        _, refused = claimed_then_refused

        if refused is None or not was_lost(refused):
            raise AssertionError(
                f"Expected the paused holder's next write refused as a lost run, got "
                f"[{None if refused is None else f'{type(refused).__name__}: {refused}'}]."
            )

        return True

    return assertion


def _it_says_the_run_was_settled() -> Assertion[Any]:
    def assertion(settled: Any) -> bool:
        if settled is not True:
            raise AssertionError(
                f"Expected settling to say the run was settled, and it said [{settled}]."
            )

        return True

    return assertion


def _it_says_the_run_was_not_settled() -> Assertion[Any]:
    def assertion(settled: Any) -> bool:
        if settled is not False:
            raise AssertionError(
                f"Expected settling by a claim since taken back to say nothing was "
                f"settled, and it said [{settled}]."
            )

        return True

    return assertion


def _the_run_is_settled_as(conn: psycopg.Connection,
                           run_id: str,
                           state: runs.RunState,
                           reason: str | None) -> Assertion[Any]:
    """Settled in `state` for `reason`, and held by nobody."""
    def assertion(_settled: Any) -> bool:
        run = runs.get(conn, run_id)
        found = (None if run is None
                 else (run.state, run.failure_reason, run.claimed_by, run.leased_until))

        if found != (state, reason, None, None):
            raise AssertionError(
                f"Expected run [{run_id}] settled as [{state}] for [{reason}], with no "
                f"holder and no lease, got (state, reason, holder, lease) [{found}]."
            )

        return True

    return assertion


def _the_run_is_as_its_holder_left_it(conn: psycopg.Connection,
                                      holder: runs.Run) -> Assertion[Any]:
    def assertion(_settled: Any) -> bool:
        run = runs.get(conn, holder.id)

        if run != holder:
            raise AssertionError(
                f"Expected the run as its holder left it, [{holder}], got [{run}]."
            )

        return True

    return assertion


def _the_run_is_still_running() -> Assertion[Any]:
    def assertion(run: Any) -> bool:
        if run is None or run.state != runs.RunState.RUNNING:
            raise AssertionError(
                f"Expected the run still running once the settling was rolled back, got "
                f"[{None if run is None else run.state}]."
            )

        return True

    return assertion


def _a_later_epoch_than(replaced: runs.Run) -> Assertion[Any]:
    def assertion(claimed: Any) -> bool:
        if claimed is None or claimed.epoch <= replaced.epoch:
            raise AssertionError(
                f"Expected the run taken back to be held under a later epoch than "
                f"[{replaced.epoch}], got "
                f"[{None if claimed is None else claimed.epoch}]."
            )

        return True

    return assertion


def _the_renewal_said_the_run_is_still_held() -> Assertion[Any]:
    def assertion(renewed_then_claimed: Any) -> bool:
        still_held, _ = renewed_then_claimed

        if still_held is not True:
            raise AssertionError(
                f"Expected the renewal to say the run is still held, and it said "
                f"[{still_held}]."
            )

        return True

    return assertion


def _nobody_else_took_it() -> Assertion[Any]:
    def assertion(renewed_then_claimed: Any) -> bool:
        _, claimed = renewed_then_claimed

        if claimed is not None:
            raise AssertionError(
                f"Expected the renewed run to stay its holder's, and [{claimed.claimed_by}] "
                f"took it."
            )

        return True

    return assertion


def _it_says_the_run_is_no_longer_held() -> Assertion[Any]:
    def assertion(still_held: Any) -> bool:
        if still_held is not False:
            raise AssertionError(
                f"Expected the renewal to say the run is no longer held, and it said "
                f"[{still_held}]."
            )

        return True

    return assertion


def _the_lease_is_as_its_holder_left_it(conn: psycopg.Connection,
                                        holder: runs.Run) -> Assertion[Any]:
    def assertion(_still_held: Any) -> bool:
        run = runs.get(conn, holder.id)
        found = None if run is None else run.leased_until

        if found != holder.leased_until:
            raise AssertionError(
                f"Expected the lease to stay as its holder left it, "
                f"[{holder.leased_until}], got [{found}]."
            )

        return True

    return assertion


def _the_run_has_no_lease(conn: psycopg.Connection, run_id: str) -> Assertion[Any]:
    def assertion(_still_held: Any) -> bool:
        run = runs.get(conn, run_id)
        found = None if run is None else run.leased_until

        if found is not None:
            raise AssertionError(
                f"Expected the settled run to have no lease, got [{found}]."
            )

        return True

    return assertion


def _the_runs_are_for(incident_ids: set[str]) -> Assertion[Any]:
    def assertion(unsettled: Any) -> bool:
        found = {run.incident_id for run in unsettled}

        if found != incident_ids:
            raise AssertionError(
                f"Expected the unsettled runs to be for incidents "
                f"{sorted(incident_ids)}, got {sorted(found)}."
            )

        return True

    return assertion


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


@pytest.mark.integration
def test_a_claimed_run_leaves_no_column_of_its_row_empty_but_its_failure() -> None:
    # The first of two, because this table has no row that carries everything:
    # a run that was claimed has a holder and a lease and has not failed, and
    # the update that records a failure is the update that clears both.
    #
    # `failure_reason` is named here rather than skipped silently, and a column
    # nobody has thought about is in neither list - so it fails both of these
    # until something writes it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_worker = "worker-that-took-it"

    with connect_from_env() as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)

        Scenario() \
            .given(
                incident_id := an_enqueued_run_for(some_alert)
            ) \
            .when(
                lambda: runs.claim(conn, some_worker, A_GENEROUS_LEASE)
            ) \
            .then(
                no_column_is_empty(conn, "incident_run", "incident_id", incident_id,
                                   except_for=["failure_reason"])
            )


@pytest.mark.integration
def test_a_failed_run_leaves_no_column_of_its_row_empty_but_its_lease() -> None:
    # The other half. A run that failed says why, and says nothing about a
    # holder or a lease - it has neither any more, and a row claiming
    # otherwise would have a worker still walking an incident nobody is
    # walking.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_reason = "the walk ran out of tool calls"

    with connect_from_env() as conn:
        an_enqueued_run_for = partial(_an_enqueued_run_for, conn)
        incident_id = an_enqueued_run_for(some_alert)
        claimed = runs.claim(conn, "worker-that-took-it", A_GENEROUS_LEASE)
        assert claimed is not None

        Scenario() \
            .when(
                lambda: runs.fail(conn, claimed, some_reason)
            ) \
            .then(
                no_column_is_empty(conn, "incident_run", "incident_id", incident_id,
                                   except_for=["claimed_by", "leased_until"])
            )


def _an_enqueued_run_for(conn: psycopg.Connection, alert: Alert) -> str:
    """An incident with a run waiting to be walked - the state the webhook
    leaves behind, and the only state a worker has anything to do in."""
    incident_id = incidents.create(conn, alert, at=utc_now())
    runs.enqueue(conn, incident_id)

    return incident_id


def _a_claimed_run_for(conn: psycopg.Connection, alert: Alert) -> runs.Run:
    """An incident whose run a worker has taken and is walking."""
    _an_enqueued_run_for(conn, alert)
    claimed = runs.claim(conn, "worker-that-took-it", A_GENEROUS_LEASE)
    assert claimed is not None

    return claimed


def _a_claim_by(conn: psycopg.Connection, worker: str, lease: timedelta) -> runs.Run:
    """The oldest run waiting, claimed by `worker` for `lease`."""
    claimed = runs.claim(conn, worker, lease)
    assert claimed is not None

    return claimed


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
