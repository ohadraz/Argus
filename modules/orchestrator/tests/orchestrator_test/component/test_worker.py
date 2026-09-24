from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, IncidentStatus
from argus_incidents.repository import incidents, runs
from argus_incidents.withdrawal import wanted_via
from argus_testkit import Assertion, Scenario, all_of
from orchestrator import worker

A_GENEROUS_LEASE = timedelta(minutes=5)

# A lease already over by the time it is written: the state a worker that was
# killed mid-walk leaves behind, arranged rather than waited for.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)

# Shorter than the walk that holds it, which is the whole point: with no
# renewal the run is taken back part-way through, and the assertion fails for
# the reason it exists.
A_LEASE_SHORTER_THAN_THE_WALK = timedelta(milliseconds=500)


@pytest.mark.component
def test_a_queued_run_is_walked_and_settled_by_the_worker(a_clean_database: None) -> None:
    # Nobody is waiting on an answer: the alert was acknowledged minutes ago
    # and its connection is long closed. What proves the walk happened is the
    # run's own state afterwards, which is the only record anything has.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_worker_reports_it_took_work(),
                _the_incident_walked_was(walked, incident_id),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_a_worker_with_nothing_to_take_says_so_rather_than_walking(a_clean_database: None) -> None:
    # The idle case, which is most of Argus's life. A worker that answered the
    # same way whether or not it found work would either sleep through a queued
    # incident or spin against an empty queue.
    dont_care_worker = "a-worker"

    def walk_that_must_not_be_called(incident_id: str) -> None:
        raise AssertionError(
            f"Expected nothing to be walked with an empty queue, got "
            f"[{incident_id}]."
        )

    with connect_from_env() as conn:
        Scenario() \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_must_not_be_called,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(
                _the_worker_reports_it_found_nothing()
            )


@pytest.mark.component
def test_a_run_whose_walk_failed_is_recorded_as_failed_with_its_reason(
    a_clean_database: None
) -> None:
    # A walk can fail for reasons that have nothing to do with the incident -
    # the model refusing, an MCP server down, a bug in a node. What must not
    # happen is that it looks like an incident still being worked: the queue is
    # the only record anything has, and a silent failure there is an incident
    # nobody knows stopped.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the read MCP server refused the connection"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_was_not_called_resolved(conn, incident_id)
            ))


@pytest.mark.component
def test_a_run_that_failed_has_its_changes_put_back(a_clean_database: None) -> None:
    # The worst moment to fail is after Code-Fix has started, because a
    # mitigation has already been applied by then. A run that ends there
    # having only written "failed" in the queue leaves production altered, no
    # postmortem written, and nothing remembered - and the walk is not coming
    # back to tidy up, because the run it would have tidied up in is the one
    # that died.
    #
    # Unwinding is what the process does with an incident that ended without
    # finishing, and a run that failed ended without finishing. That it is
    # already the answer for a withdrawn incident is not a reason to give a
    # different one here: the world is in the same state either way, and
    # `unwind_incident` is written to be safe over an incident that had
    # already tidied up after itself.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the model was rate limited partway through the walk"
    unwound: list[str] = []

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_fails,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_incident_unwound_was(unwound, incident_id),
                _the_run_is_failed(conn, incident_id, what_went_wrong)
            ))


@pytest.mark.component
def test_an_unwind_that_fails_after_a_failed_run_still_records_the_failure(
    a_clean_database: None
) -> None:
    # Two failures in a row, and the second must not eat the first. The queue
    # is the only record anything has that this incident stopped; if putting
    # the changes back throws and takes the whole handler with it, the run
    # stays claimed until its lease expires and the reason it failed is never
    # written down anywhere.
    #
    # The reason recorded is the walk's, not the unwind's. What a human needs
    # to know is why the incident stopped being worked - that tidying up
    # afterwards also went wrong is a second fact, and it belongs in the log
    # rather than in place of the first.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the model was rate limited partway through the walk"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    def unwind_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("the flag provider could not be reached either")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_fails,
                    unwind=unwind_that_fails,
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(
                _the_run_is_failed(conn, incident_id, what_went_wrong)
            )


@pytest.mark.component
def test_a_run_whose_incident_was_withdrawn_is_never_walked(a_clean_database: None) -> None:
    # Withdrawn before anybody took it. Walking it would start an investigation
    # into an incident a human already has in hand - and `run_incident`'s first
    # act is to mark it `investigating`, which would take a finished incident
    # and put it back on the board.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id)
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    still_wanted=wanted_via(connect_from_env),
                    unwind=_an_unwind_recording_what_it_was_given([])
                )
            ) \
            .then(all_of(
                _the_worker_reports_it_took_work(),
                _nothing_was_walked(walked),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_a_withdrawn_incident_has_its_changes_put_back(a_clean_database: None) -> None:
    # The other half of stopping. A walk halted mid-flight has left production
    # in a state it chose for a reason that no longer applies, and the run is
    # not finished until that is put back.
    dont_care_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id)
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=_a_walk_that_must_not_be_called(),
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(
                _the_incident_unwound_was(unwound, incident_id)
            )


@pytest.mark.component
def test_an_incident_withdrawn_while_it_was_walked_is_unwound_afterwards(
    a_clean_database: None
) -> None:
    # The ordinary case, and the reason the question is asked twice: the walk
    # was live when it was claimed and stopped somewhere in the middle, so
    # nothing before it started could have known.
    dont_care_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        def walk_that_is_withdrawn_partway(withdrawn_id: str) -> None:
            incidents.withdraw(conn, withdrawn_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_withdrawn_partway,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    still_wanted=wanted_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_incident_unwound_was(unwound, incident_id),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_a_run_abandoned_mid_walk_is_taken_up_for_the_same_incident(a_clean_database: None) -> None:
    # The failure this exists to prevent is not "the run is lost" but "the run
    # is done twice": an incident picked up as a new one would investigate a
    # fault already investigated and mitigate one already mitigated. So what is
    # asserted is that the second worker walks the *same* incident, and that
    # nothing new was created for it to walk.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_that_stopped = "worker-that-was-killed-mid-walk"
    the_worker_that_came_after = "worker-that-started-next"
    walked: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                runs.claim(conn, the_worker_that_stopped, A_LEASE_ALREADY_OVER)
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    the_worker_that_came_after,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    unwind=_an_unwind_that_must_not_be_called(),
                    still_wanted=wanted_via(connect_from_env),
                )
            ) \
            .then(all_of(
                _the_incident_walked_was(walked, incident_id),
                _only_one_incident_exists(conn),
                _only_one_run_exists(conn),
            ))


@pytest.mark.component
def test_a_run_still_being_walked_keeps_its_claim(a_clean_database: None) -> None:
    # The mirror of the test above, and the one that was missing. A lease says
    # how long before a *stopped* worker's run is taken back; it is not a budget
    # for the walk, which Code-Fix alone is allowed to outlast. So the claim has
    # to be renewed while the walk runs - and until it was, a walk that outlived
    # its lease had the same run taken up beneath it and resumed from its
    # checkpoint: two walks of one incident, both calling the model, both free to
    # act on the world.
    #
    # Found in a recording corpus, of all places. One walk's answers were stored
    # under another walk's name, because both were live at once.
    #
    # The lease is shorter than the walk on purpose, so the renewal has to happen
    # for this to hold rather than merely be allowed to.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_walking_it = "worker-part-way-through-a-long-walk"
    the_worker_that_came_after = "worker-that-should-find-nothing"
    taken_from_under_it: list[str] = []

    def walk_outlasting_its_lease(dont_care_incident_id: str) -> None:
        time.sleep(A_LEASE_SHORTER_THAN_THE_WALK.total_seconds() * 3)

        with connect_from_env() as second:
            claimed = runs.claim(second, the_worker_that_came_after, A_GENEROUS_LEASE)

            if claimed is not None:
                taken_from_under_it.append(claimed.incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert)
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(incident_id) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    the_worker_walking_it,
                    A_LEASE_SHORTER_THAN_THE_WALK,
                    walk=walk_outlasting_its_lease,
                    unwind=_an_unwind_that_must_not_be_called(),
                    still_wanted=wanted_via(connect_from_env),
                    connections=connect_from_env,
                )
            ) \
            .then(_no_second_worker_took_the_run(taken_from_under_it))


def _no_second_worker_took_the_run(taken: list[str]) -> Assertion[bool]:
    """That nobody could claim the run while its own worker was still walking it.

    Asserted as what a second worker *got* rather than as a lease timestamp: a
    renewal that moved the deadline but not far enough would satisfy a test
    reading the column and still hand the run away.
    """
    def assertion(dont_care_took_work: bool) -> bool:
        if taken:
            raise AssertionError(
                f"Expected the run to stay claimed while it was walked; a second "
                f"worker took {taken}."
            )

        return True

    return assertion


def _the_run_is_failed(conn: psycopg.Connection,
                       incident_id: str,
                       reason: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)

        if run is None:
            raise AssertionError(f"No run found for incident [{incident_id}].")

        if run.state != runs.RunState.FAILED:
            raise AssertionError(
                f"Expected the run to be recorded as [{runs.RunState.FAILED}], "
                f"got [{run.state}]."
            )

        if run.failure_reason is None or reason not in run.failure_reason:
            raise AssertionError(
                f"Expected the recorded reason to say [{reason}], got "
                f"[{run.failure_reason}]."
            )

        return True

    return assertion


def _the_incident_was_not_called_resolved(conn: psycopg.Connection,
                                          incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status == IncidentStatus.RESOLVED:
            raise AssertionError(
                "Expected an incident whose walk failed not to be recorded as "
                "resolved."
            )

        return True

    return assertion


def _the_worker_reports_it_took_work() -> Assertion[bool]:
    def assertion(took_work: bool) -> bool:
        if took_work is not True:
            raise AssertionError(
                f"Expected the worker to report it took a run, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_worker_reports_it_found_nothing() -> Assertion[bool]:
    def assertion(took_work: bool) -> bool:
        if took_work is not False:
            raise AssertionError(
                f"Expected the worker to report an empty queue, got [{took_work!r}]."
            )

        return True

    return assertion


def _the_incident_walked_was(walked: list[str], incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if walked != [incident_id]:
            raise AssertionError(
                f"Expected the worker to walk incident [{incident_id}] exactly "
                f"once, got {walked}."
            )

        return True

    return assertion


def _the_run_is_done(conn: psycopg.Connection, incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)

        if run is None:
            raise AssertionError(f"No run found for incident [{incident_id}].")

        if run.state != runs.RunState.DONE:
            raise AssertionError(
                f"Expected the walked run to be settled as "
                f"[{runs.RunState.DONE}], got [{run.state}]."
            )

        if run.claimed_by is not None:
            raise AssertionError(
                f"Expected a settled run to be held by nobody, got "
                f"[{run.claimed_by}]."
            )

        return True

    return assertion


def _a_walk_that_must_not_be_called() -> Callable[[str], None]:
    def walk(incident_id: str) -> None:
        raise AssertionError(
            f"Expected a withdrawn incident not to be walked, got [{incident_id}]."
        )

    return walk


def _an_unwind_recording_what_it_was_given(unwound: list[str]) -> Callable[[str], None]:
    def unwind(incident_id: str) -> None:
        unwound.append(incident_id)

    return unwind


def _nothing_was_walked(walked: list[str]) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if walked:
            raise AssertionError(
                f"Expected a withdrawn incident not to be walked, got {walked}."
            )

        return True

    return assertion


def _the_incident_unwound_was(unwound: list[str],
                              incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if unwound != [incident_id]:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be unwound exactly once, "
                f"got {unwound}."
            )

        return True

    return assertion


def _an_unwind_that_must_not_be_called() -> Callable[[str], None]:
    def unwind(incident_id: str) -> None:
        raise AssertionError(
            f"Expected a resumed run nobody withdrew not to be unwound, got "
            f"[{incident_id}]."
        )

    return unwind


def _only_one_run_exists(conn: psycopg.Connection) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM incident_run")
            row = cursor.fetchone()

        if row is None or row[0] != 1:
            raise AssertionError(
                f"Expected the abandoned run to be taken up rather than "
                f"replaced, got {row[0] if row else 'no'} runs."
            )

        return True

    return assertion


def _only_one_incident_exists(conn: psycopg.Connection) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM incident")
            row = cursor.fetchone()

        if row is None or row[0] != 1:
            raise AssertionError(
                f"Expected the resumed incident to be the only one, got "
                f"{row[0] if row else 'no'} incidents."
            )

        return True

    return assertion
