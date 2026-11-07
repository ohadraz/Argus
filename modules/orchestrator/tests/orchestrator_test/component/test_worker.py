from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from argus_core import (
    Connections,
    Fence,
    Holding,
    RunLost,
    connect_from_env,
    fence,
    get_settings,
    utc_now,
)
from argus_core.events import StatusChanged
from argus_core.llm import ModelUnavailable
from argus_core.models import REVERT_FEATURE_FLAG, ActionProgress, Alert, IncidentStatus
from argus_core.telemetry import ARGUS_INCIDENT_ID, ARGUS_RUN_ID
from argus_incidents.ending import EndedByAPerson, ended_by_a_person_via
from argus_incidents.repository import events, hypotheses, incidents, runs, taken_actions
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    calling,
    one_record_was_logged,
)
from opentelemetry import baggage
from orchestrator import worker
from psycopg.pq import TransactionStatus

from orchestrator_test.framework.builders import a_determined_hypothesis
from orchestrator_test.framework.observing import Observed, observing

A_GENEROUS_LEASE = timedelta(minutes=5)

# Who takes a run back from a worker that was paused past its lease.
THE_WORKER_THAT_TOOK_IT_BACK = "worker-that-took-it-back"

# Where the worker's own lines are logged from.
THE_WORKER = "orchestrator.worker"

# What a worker's connections are called, and so what the database refuses a
# write from when it names no run. Stated rather than imported: it is the one
# word the worker and the schema agree on.
THE_WORKERS_CONNECTIONS = "argus-worker"

# Refused because a worker wrote without saying which run it writes for.
NO_RUN_HELD = "AR002"

# A lease already over by the time it is written: the state a worker that was
# killed mid-walk leaves behind, arranged rather than waited for.
A_LEASE_ALREADY_OVER = timedelta(seconds=-1)

# Shorter than the walk that holds it, which is the whole point: with no
# renewal the run is taken back part-way through, and the assertion fails for
# the reason it exists.
A_LEASE_SHORTER_THAN_THE_WALK = timedelta(milliseconds=500)

# The context an incident kept from the span its alert was received in, as the
# propagator wrote it: a trace, and the span within it.
SOME_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SOME_SPAN = "00f067aa0ba902b7"
SOME_TRACE_CONTEXT = {"traceparent": f"00-{SOME_TRACE}-{SOME_SPAN}-01"}

# How a worker tries again a walk the model could not answer for now: three
# tries, the first wait a minute.
SOME_TRYING_AGAIN = worker.TryingAgain(attempts=3, first_wait=timedelta(minutes=1))

# Long enough for everything between a run being requeued and its wait being
# read, and far shorter than any wait it is told apart from.
A_MOMENT_THE_TEST_TAKES = timedelta(seconds=30)


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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_was_not_called_resolved(conn, incident_id)
            ))


@pytest.mark.component
def test_an_incident_whose_walk_failed_is_escalated_rather_than_left_mid_walk(
    a_clean_database: None
) -> None:
    # The run is not the incident. Its neighbour above asserts the queue
    # records the failure, which it does - and a person reading the incident
    # sees none of that: the walk set `mitigating` on the way in, raised, and
    # left it there. Nothing re-claims a failed run, so the status is not a
    # phase the incident is passing through. It is where the incident stays.
    #
    # `escalated` because that is what the walk means by "a human is needed and
    # Argus has no move left", and an exception nobody planned for is the
    # clearest case of it. What is wrong with `mitigating` is not that it is
    # untidy: it says Argus is acting, so the page offers no reason to look, and
    # the one incident that needs a person is the one that does not ask for one.
    #
    # Staged at `mitigating` rather than at whatever `create` leaves behind,
    # because that is the status the two observed failures stranded - a walk
    # that had taken an action and was in its verification wait when
    # the read it was waiting on raised.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    # A bare exception from the walk seam, and deliberately not a failure of
    # anything the walk does. A read that times out inside the verification
    # window is the failure that prompted this, and it is going to stop being
    # unhandled - so a test resting on it would be a test the next change
    # rewrites. What this asserts is the backstop: whatever goes unhandled,
    # wherever, the incident does not stay mid-walk.
    something_nobody_planned_for = "a bug in a node nobody has written yet"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(something_nobody_planned_for)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id,
                                   something_nobody_planned_for),
                _the_incident_is(conn, incident_id, IncidentStatus.ESCALATED)
            ))


@pytest.mark.component
def test_an_incident_a_failed_walk_escalated_ends_when_its_account_says(
    a_clean_database: None
) -> None:
    # The row's end and the line saying the walk stopped are one instant: the
    # database's own clock dated the end before the line that announced it.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("dont care")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                _it_ended_when_the_account_says_it_was(conn, incident_id,
                                                       IncidentStatus.ESCALATED)
            )


@pytest.mark.component
def test_a_run_that_failed_has_its_changes_put_back(a_clean_database: None) -> None:
    # Failed before the walk reached an ending: a change it made may be
    # standing for a reason nobody will now finish judging - a flag reverted,
    # its verification never read. A run that ends there having only written
    # "failed" in the queue leaves production altered, and the walk is not
    # coming back to tidy up, because the run it would have tidied up in is the
    # one that died.
    #
    # Unwinding is what the process does with an incident that ended without
    # finishing, and a run that failed before an ending ended without
    # finishing. That it is already the answer for a withdrawn incident is not
    # a reason to give a different one here: the world is in the same state
    # either way, and `unwind_incident` is written to be safe over an incident
    # that had already tidied up after itself.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "a bug in a node nobody has written yet"
    unwound: list[str] = []

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
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
    what_went_wrong = "a bug in a node nobody has written yet"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    def unwind_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("the flag provider could not be reached either")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=_a_walk_that_must_not_be_called(),
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_withdrawn_partway(withdrawn_id: str) -> None:
            incidents.withdraw(conn, withdrawn_id, at=utc_now())

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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_incident_unwound_was(unwound, incident_id),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_a_withdrawn_incident_whose_walk_then_failed_is_not_announced_escalated(
    a_clean_database: None
) -> None:
    # Withdrawn partway, and the walk raised on its way out. The person who
    # withdrew it has it in hand, so the row stays withdrawn - and the account
    # must not tell everyone watching that it was escalated to somebody.
    dont_care_alert = Alert(service="tuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_withdrawn_and_then_fails(withdrawn_id: str) -> None:
            incidents.withdraw(conn, withdrawn_id, at=utc_now())
            raise RuntimeError("a bug in a node nobody has written yet")

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_withdrawn_and_then_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                _the_account_never_said_it_was(conn, incident_id, IncidentStatus.ESCALATED)
            )


@pytest.mark.component
def test_a_run_whose_incident_was_resolved_before_it_was_claimed_is_walked(
    a_clean_database: None
) -> None:
    # Resolved while it was still queued. Unlike a withdrawal, the person is
    # owed a write-up, and the walk is what writes one - so it is walked, and
    # it goes straight to remembering and the postmortem.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    walked: list[str] = []
    unwound: list[str] = []

    def walk_recording_what_it_was_given(incident_id: str) -> None:
        walked.append(incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incidents.resolve(conn, incident_id, at=utc_now())
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_what_it_was_given,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_incident_walked_was(walked, incident_id),
                _nothing_was_unwound(unwound),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_an_incident_resolved_while_it_was_walked_is_not_unwound(
    a_clean_database: None
) -> None:
    # The person who reported it over has the world as it is. Putting Argus's
    # changes back behind them would be Argus second-guessing the one report it
    # does not test.
    dont_care_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_resolved_partway(resolved_id: str) -> None:
            incidents.resolve(conn, resolved_id, at=utc_now())

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_resolved_partway,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _nothing_was_unwound(unwound),
                _the_run_is_done(conn, incident_id)
            ))


@pytest.mark.component
def test_a_resolved_incident_whose_walk_then_failed_is_not_unwound(
    a_clean_database: None
) -> None:
    # The one place a resolution could undo what it promised to leave alone: a
    # failed run is unwound, and a write-up that raised after the person
    # reported the incident over is a failed run. The run is still recorded as
    # failed, and the incident stays as the person left it.
    dont_care_alert = Alert(service="tuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the postmortem's model refused"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_resolved_and_then_fails(resolved_id: str) -> None:
            incidents.resolve(conn, resolved_id, at=utc_now())
            raise RuntimeError(what_went_wrong)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_resolved_and_then_fails,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _nothing_was_unwound(unwound),
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_is(conn, incident_id, IncidentStatus.RESOLVED)
            ))


@pytest.mark.component
@pytest.mark.parametrize("ending", [IncidentStatus.MITIGATED, IncidentStatus.ESCALATED,
                                    IncidentStatus.RECOMMENDED, IncidentStatus.DISPROVEN])
def test_an_incident_its_walk_had_ended_is_left_as_the_walk_left_it_when_the_run_fails(
    ending: IncidentStatus, a_clean_database: None
) -> None:
    # The walk reached its ending and then failed in what comes after it - the
    # write-up above all. Escalating there would call a mitigated incident one a
    # person must take over, and putting the changes back would undo the fix the
    # walk confirmed. The incident stays as the walk left it, and only the run
    # says something went wrong.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the request did not match the recording"
    unwound: list[str] = []

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, ending, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_is(conn, incident_id, ending),
                _nothing_was_put_back(unwound),
                _the_account_never_said_it_was(conn, incident_id, IncidentStatus.ESCALATED)
            ))


@pytest.mark.component
@pytest.mark.parametrize("where", [IncidentStatus.MITIGATING, IncidentStatus.MITIGATED])
def test_a_walk_the_model_could_not_answer_for_now_is_requeued_to_try_again(
    where: IncidentStatus, a_clean_database: None
) -> None:
    # The model was overloaded, rate limited or out of reach when the walk
    # asked it - mid-mitigation, or in the write-up after the walk had
    # mitigated the incident. Nothing about the incident is wrong, and a minute
    # later the same question gets an answer. So the run goes back in line to
    # go on from where it stopped: the incident as it was, nothing put back,
    # and the walk's claims left for the walk that resumes to answer.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, where, at=utc_now())
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
                    walk=_a_walk_that_claims_an_action_and_fails(
                        failing_with=ModelUnavailable("the model could not be reached for now")
                    ),
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(all_of(
                _the_run_waits_to_be_tried_again(conn, incident_id, retries=1),
                _the_incident_is(conn, incident_id, where),
                _nothing_was_put_back(unwound),
                _its_actions_are_seen_as(incident_id, [ActionProgress.CLAIMED])
            ))


@pytest.mark.component
@pytest.mark.parametrize("retries_before", [0, 1])
def test_a_run_requeued_waits_longer_each_time(
    retries_before: int, a_clean_database: None
) -> None:
    # A minute, then five: an outage that outlasted one wait is one a second
    # wait of the same length is likelier to land inside than past.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_the_model_could_not_answer(dont_care_incident_id: str) -> None:
        raise ModelUnavailable("the model could not be reached for now")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)
        _requeued_before(conn, incident_id, retries_before)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_the_model_could_not_answer,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(
                _the_run_waits_about(conn, incident_id,
                                     SOME_TRYING_AGAIN.first_wait * 5 ** retries_before)
            )


@pytest.mark.component
def test_a_walk_the_model_could_not_answer_on_its_last_try_fails(a_clean_database: None) -> None:
    # Every try spent, and the model still out of reach: the run fails, as any
    # other failure does - and the incident the walk had mitigated stays so.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the model could not be reached for now"
    unwound: list[str] = []

    def walk_the_model_could_not_answer(dont_care_incident_id: str) -> None:
        raise ModelUnavailable(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATED, at=utc_now())
        runs.enqueue(conn, incident_id)
        _requeued_before(conn, incident_id, SOME_TRYING_AGAIN.attempts - 1)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_the_model_could_not_answer,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_is(conn, incident_id, IncidentStatus.MITIGATED),
                _nothing_was_put_back(unwound)
            ))


@pytest.mark.component
def test_a_walk_the_model_could_not_answer_on_its_last_try_mid_walk_is_escalated_and_put_back(
    a_clean_database: None
) -> None:
    # Every try spent before the walk reached an ending: the run fails as any
    # other failure there does - escalated, and its changes put back - with the
    # model's being out of reach as the reason.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the model could not be reached for now"
    unwound: list[str] = []

    def walk_the_model_could_not_answer(dont_care_incident_id: str) -> None:
        raise ModelUnavailable(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
        runs.enqueue(conn, incident_id)
        _requeued_before(conn, incident_id, SOME_TRYING_AGAIN.attempts - 1)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_the_model_could_not_answer,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(all_of(
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_is(conn, incident_id, IncidentStatus.ESCALATED),
                _the_incident_unwound_was(unwound, incident_id)
            ))


@pytest.mark.component
def test_a_failed_run_whose_ending_cannot_be_read_is_not_unwound(
    a_clean_database: None
) -> None:
    # The database went away with the walk. Unwinding blind could undo the
    # mitigations of an incident a person resolved, which is the error a
    # resolution exists to prevent; leaving a change in place is the one of the
    # two a person can put right.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "the database went away"
    unwound: list[str] = []

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=_readable_only_before_the_walk()
                )
            ) \
            .then(all_of(
                _nothing_was_unwound(unwound),
                _the_run_is_failed(conn, incident_id, what_went_wrong)
            ))


@pytest.mark.component
def test_a_failed_run_whose_incident_cannot_be_read_is_escalated_and_not_unwound(
    a_clean_database: None
) -> None:
    # The database could not say how the incident stood once the walk failed.
    # Putting back blind could undo the fix of an incident the walk had
    # mitigated; leaving a change in place is the one of the two a person can
    # put right. Whether to escalate is the statement's to decide, not the
    # read's, so a walk that stopped mid-way is still handed to a person rather
    # than left reading as work in progress.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    what_went_wrong = "a bug in a node nobody has written yet"
    unwound: list[str] = []

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError(what_went_wrong)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    connections=_connections_only_before_the_walk()
                )
            ) \
            .then(all_of(
                _nothing_was_put_back(unwound),
                _the_run_is_failed(conn, incident_id, what_went_wrong),
                _the_incident_is(conn, incident_id, IncidentStatus.ESCALATED)
            ))


@pytest.mark.component
def test_a_claim_a_failed_walk_left_open_is_settled_as_unknown(a_clean_database: None) -> None:
    # A failed run is never taken again, so no walk will answer a claim it left
    # open - and left as a claim, it reads as an action still in flight for
    # good. Settled with the run, so a connection of its own sees it.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    walk=_a_walk_that_claims_an_action_and_fails(),
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                _its_actions_are_seen_as(incident_id, [ActionProgress.UNKNOWN])
            )


@pytest.mark.component
def test_a_dead_workers_claim_on_an_incident_withdrawn_meanwhile_is_settled_as_unknown(
    a_clean_database: None
) -> None:
    # The run taken back from a dead worker, and found withdrawn: unwound,
    # never walked, and finished - so nothing will ever answer the claim the
    # dead worker left open.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_worker_that_stopped = "worker-that-was-killed-mid-walk"
    the_worker_that_came_after = "worker-that-started-next"
    unwound: list[str] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)
        runs.claim(conn, the_worker_that_stopped, A_LEASE_ALREADY_OVER)
        _an_action_claimed_on(conn, incident_id)

        Scenario() \
            .given(
                incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    the_worker_that_came_after,
                    A_GENEROUS_LEASE,
                    walk=_a_walk_that_must_not_be_called(),
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_incident_unwound_was(unwound, incident_id),
                _its_actions_are_seen_as(incident_id, [ActionProgress.UNKNOWN])
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
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
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    connections=connect_from_env,
                )
            ) \
            .then(_no_second_worker_took_the_run(taken_from_under_it))


@pytest.mark.component
def test_a_run_is_worked_inside_the_trace_its_incident_kept(a_clean_database: None) -> None:
    # Which is what makes an incident one trace from its alert: the run's span
    # is a child of the span the alert was received in, however long after and
    # in whichever process, and the walk's span hangs from the run's.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    observed = observing()

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, trace_context=SOME_TRACE_CONTEXT,
                                       at=utc_now())
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
                    walk=lambda dont_care_incident_id: None,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    tracer=observed.tracer
                )
            ) \
            .then(
                _the_run_continued_the_trace_its_incident_kept(observed, conn, incident_id)
            )


@pytest.mark.component
def test_a_walk_runs_with_its_incident_and_its_run_in_the_baggage(
    a_clean_database: None
) -> None:
    # So every log line written anywhere in the walk - in a node, in an agent,
    # in a server answering one of its tool calls - says whose incident it was
    # and which run of it, without anybody passing either down.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    seen: list[dict[str, object]] = []

    def walk_recording_the_baggage(dont_care_incident_id: str) -> None:
        seen.append(dict(baggage.get_all()))

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    walk=walk_recording_the_baggage,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                _the_walk_saw_its_incident_and_run(seen, conn, incident_id)
            )


@pytest.mark.component
def test_a_run_is_logged_as_it_is_claimed_and_as_it_finishes(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The two ends of a run, and which worker held it - the first thing asked
    # of a run that is taking too long is where it is.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_worker = "some-host/4242"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO)),
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    some_worker,
                    A_GENEROUS_LEASE,
                    walk=lambda dont_care_incident_id: None,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                one_record_was_logged(caplog, THE_WORKER, logging.INFO, "run claimed",
                                      values={"worker": some_worker}),
                one_record_was_logged(caplog, THE_WORKER, logging.INFO, "run finished")
            ))


@pytest.mark.component
def test_a_run_whose_walk_failed_is_logged_with_what_failed(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Work lost: the incident stops being worked, and a person has to look.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("some failure nobody planned for")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.ERROR, "run failed",
                                      failure=RuntimeError)
            )


@pytest.mark.component
def test_an_unwind_that_failed_after_a_failed_run_is_logged_with_what_failed(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The worse of the two failures: whatever the walk changed may still be
    # changed, and nothing else is going to put it back.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("some failure nobody planned for")

    def unwind_that_fails(dont_care_incident_id: str) -> None:
        raise ConnectionError("some provider that could not be reached")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.ERROR,
                                      "changes could not be put back after a failed run",
                                      failure=ConnectionError)
            )


@pytest.mark.component
def test_a_failed_run_left_alone_because_a_person_resolved_it_is_logged(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # A failed run is otherwise put back, so a reader of the log seeing a
    # failure and no unwind needs to be told it was deliberate.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_resolved_and_then_fails(resolved_id: str) -> None:
            incidents.resolve(conn, resolved_id, at=utc_now())
            raise RuntimeError("some failure nobody planned for")

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO)),
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_resolved_and_then_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.INFO,
                                      "incident resolved by a person, leaving its changes "
                                      "in place")
            )


@pytest.mark.component
def test_a_run_requeued_to_try_again_is_logged_with_what_failed(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Not work lost, so not "run failed": the run will be taken up again, and a
    # reader needs to know which try this was and why.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_the_model_could_not_answer(dont_care_incident_id: str) -> None:
        raise ModelUnavailable("the model could not be reached for now")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    walk=walk_the_model_could_not_answer,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(all_of(
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run requeued to try again", values={"retries": 1},
                                      failure=ModelUnavailable),
                _it_was_never_logged(caplog, "run failed")
            ))


@pytest.mark.component
def test_a_failed_run_left_alone_because_its_walk_had_ended_it_is_logged(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # A failed run is otherwise escalated and put back, so a reader of the log
    # seeing neither needs to be told it was deliberate.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("some failure nobody planned for")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATED, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO)),
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.INFO,
                                      "incident ended by its walk, leaving it as the walk "
                                      "left it")
            )


@pytest.mark.component
def test_a_failed_run_whose_incident_cannot_be_read_is_logged_with_what_failed(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing was put back, and whether anything should have been is unknown.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("some failure nobody planned for")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    connections=_connections_only_before_the_walk()
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.ERROR,
                                      "how the incident stood could not be read after a "
                                      "failed run, so nothing was put back",
                                      failure=ConnectionError)
            )


@pytest.mark.component
def test_a_failed_run_whose_ending_cannot_be_read_is_logged_with_what_failed(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing was put back, and whether anything should have been is unknown -
    # a change of Argus's may still be standing, and somebody has to look.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk_that_fails(dont_care_incident_id: str) -> None:
        raise RuntimeError("some failure nobody planned for")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    ended_by_a_person=_readable_only_before_the_walk()
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.ERROR,
                                      "whether a person ended the incident could not be "
                                      "read after a failed run, so nothing was put back",
                                      failure=RuntimeError)
            )


@pytest.mark.component
@pytest.mark.parametrize("walked", [False, True])
def test_a_withdrawn_incident_is_logged_as_it_is_unwound(
    walked: bool, a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Withdrawn before the walk, or during it: the same line, saying which,
    # because "never investigated" and "stopped partway" send a reader to
    # different places.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_that_is_withdrawn_partway(withdrawn_id: str) -> None:
            incidents.withdraw(conn, withdrawn_id, at=utc_now())

        if not walked:
            incidents.withdraw(conn, incident_id, at=utc_now())

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.INFO)),
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_is_withdrawn_partway,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                one_record_was_logged(caplog, THE_WORKER, logging.INFO,
                                      "incident withdrawn, unwinding",
                                      values={"walked": walked})
            )


@pytest.mark.component
def test_a_walk_runs_with_no_transaction_left_open_on_the_workers_connection(
    a_clean_database: None
) -> None:
    # Anything the worker reads and leaves uncommitted before walking is a
    # transaction open for the whole walk, and DDL waits for every open
    # transaction to end - the schema job's drop among it, hung behind a walk
    # that could take half an hour.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    seen: list[TransactionStatus] = []

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, trace_context=SOME_TRACE_CONTEXT,
                                       at=utc_now())
        runs.enqueue(conn, incident_id)

        def walk_recording_the_connection(dont_care_incident_id: str) -> None:
            seen.append(conn.info.transaction_status)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_recording_the_connection,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(
                _the_walk_found_no_transaction_open(seen)
            )


@pytest.mark.component
def test_a_failed_walk_whose_run_was_taken_back_leaves_both_to_the_new_holder(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The worker was paused past its lease, and the run was taken back while it
    # was. Failing the run, escalating the incident or settling its claims would
    # be the old holder ending a walk somebody else is part-way through.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "worker-that-was-paused"

    def walk_that_loses_its_run_then_fails(incident_id: str) -> None:
        _an_action_claimed_on_its_own_connection(incident_id)
        _the_run_taken_from_under_it(incident_id)

        raise RuntimeError("dont care")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
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
                    walk=walk_that_loses_its_run_then_fails,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_held_by(conn, incident_id, THE_WORKER_THAT_TOOK_IT_BACK),
                _the_incident_is(conn, incident_id, IncidentStatus.MITIGATING),
                _its_actions_are_seen_as(incident_id, [ActionProgress.CLAIMED]),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now")
            ))


@pytest.mark.component
def test_a_finished_walk_whose_run_was_taken_back_leaves_it_to_the_new_holder(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The same, for a walk that went on to its end: finishing the run would end
    # it under the walk that took it back.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "worker-that-was-paused"

    def walk_that_loses_its_run(incident_id: str) -> None:
        _an_action_claimed_on_its_own_connection(incident_id)
        _the_run_taken_from_under_it(incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    walk=walk_that_loses_its_run,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_held_by(conn, incident_id, THE_WORKER_THAT_TOOK_IT_BACK),
                _its_actions_are_seen_as(incident_id, [ActionProgress.CLAIMED]),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now")
            ))


@pytest.mark.component
def test_a_walk_the_model_could_not_answer_whose_run_was_taken_back_leaves_it_to_the_new_holder(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Paused past its lease, the run taken back, and only then the model's
    # failure arrives. Requeueing the run from here would take it from the
    # worker walking it now.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "worker-that-was-paused"

    def walk_that_loses_its_run_then_cannot_get_an_answer(incident_id: str) -> None:
        _the_run_taken_from_under_it(incident_id)

        raise ModelUnavailable("the model could not be reached for now")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
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
                    walk=walk_that_loses_its_run_then_cannot_get_an_answer,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    trying_again=SOME_TRYING_AGAIN
                )
            ) \
            .then(all_of(
                _the_run_is_held_by(conn, incident_id, THE_WORKER_THAT_TOOK_IT_BACK),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now"),
                _it_was_never_logged(caplog, "run requeued to try again")
            ))


@pytest.mark.component
def test_a_walk_told_its_run_was_lost_is_neither_put_back_nor_settled(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Told by a store that refused its write. What the walk changed is the new
    # holder's to judge now, and putting it back from here would undo a walk
    # still under way.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_worker = "worker-that-was-paused"
    unwound: list[str] = []

    def walk_told_its_run_was_lost(incident_id: str) -> None:
        _an_action_claimed_on_its_own_connection(incident_id)

        raise RunLost("a newer claim holds this run")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    some_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_told_its_run_was_lost,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _nothing_was_put_back(unwound),
                _the_run_is_held_by(conn, incident_id, some_worker),
                _the_incident_is(conn, incident_id, IncidentStatus.MITIGATING),
                _its_actions_are_seen_as(incident_id, [ActionProgress.CLAIMED]),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now"),
                _it_was_never_logged(caplog, "run failed")
            ))


@pytest.mark.component
@pytest.mark.parametrize("withdrawn", [False, True], ids=["walk-failed", "withdrawn"])
def test_an_unwind_told_its_run_was_lost_settles_nothing_and_says_so_once(
    withdrawn: bool, a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The put-back's own write refused: a lost run, not changes that could not
    # be put back - and no escalation follows it.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_worker = "worker-that-was-paused"

    def walk(incident_id: str) -> None:
        if withdrawn:
            with connect_from_env() as conn:
                incidents.withdraw(conn, incident_id, at=utc_now())
        else:
            raise RuntimeError("dont care")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    some_worker,
                    A_GENEROUS_LEASE,
                    walk=walk,
                    unwind=_an_unwind_told_its_run_was_lost(),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                )
            ) \
            .then(all_of(
                _the_run_is_held_by(conn, incident_id, some_worker),
                _the_incident_was_not_escalated(conn, incident_id),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now"),
                _it_was_never_logged(caplog, "changes could not be put back after a failed run")
            ))


@pytest.mark.component
@pytest.mark.parametrize("ended", ["walked", "withdrawn", "failed"])
def test_a_run_is_held_by_the_process_for_as_long_as_it_is_worked_and_no_longer(
    ended: str, a_clean_database: None
) -> None:
    # What every connection the walk and the unwind are handed is fenced with:
    # the run as this claim holds it, and between runs none. The unwind writes
    # through the same pool as the walk, after a withdrawal and in the put-back
    # after a failed walk alike.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"
    holding = Holding()
    held_during: list[Fence | None] = []

    def walk_seeing_what_is_held(dont_care_incident_id: str) -> None:
        held_during.append(holding.current())

        if ended == "failed":
            raise RuntimeError("dont care")

    def unwind_seeing_what_is_held(dont_care_incident_id: str) -> None:
        held_during.append(holding.current())

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        runs.enqueue(conn, incident_id)

        if ended == "withdrawn":
            incidents.withdraw(conn, incident_id, at=utc_now())

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_seeing_what_is_held,
                    unwind=unwind_seeing_what_is_held,
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    holding=holding
                )
            ) \
            .then(
                _held_while_worked_and_not_after(conn, incident_id, held_during, holding,
                                                 times_asked=2 if ended == "failed" else 1)
            )


@pytest.mark.component
@pytest.mark.parametrize("lost", [False, True], ids=["settled", "lost"])
def test_the_workers_own_connection_writes_for_no_run_once_its_run_is_over(
    lost: bool, a_clean_database: None
) -> None:
    # The fence came down whether the run was settled under it or lost from
    # under it: a write on the connection between runs is a worker's write for
    # nothing, and refused.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    dont_care_worker = "a-worker"

    def walk(incident_id: str) -> None:
        if lost:
            _the_run_taken_from_under_it(incident_id)

    with (
        connect_from_env() as setting_up,
        _a_connection_named(THE_WORKERS_CONNECTIONS) as conn
    ):
        incident_id = incidents.create(setting_up, dont_care_alert, at=utc_now())
        runs.enqueue(setting_up, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: (worker.take_one_run(
                    conn,
                    dont_care_worker,
                    A_GENEROUS_LEASE,
                    walk=walk,
                    unwind=_an_unwind_recording_what_it_was_given([]),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env)
                ), attempting(lambda: _a_write_on(conn, incident_id))())
            ) \
            .then(all_of(
                (_the_run_is_held_by(setting_up, incident_id, THE_WORKER_THAT_TOOK_IT_BACK)
                 if lost else _the_run_is_done(setting_up, incident_id)),
                _the_write_after_it_was_refused_as(NO_RUN_HELD)
            ))


@pytest.mark.component
def test_a_walk_whose_write_was_refused_for_a_lost_run_is_neither_put_back_nor_settled(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The database refused it rather than anything in the walk noticing: what
    # reaches the worker is the store's own error, and it means what `RunLost`
    # means.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_worker = "worker-that-was-paused"
    holding = Holding()
    unwound: list[str] = []

    def walk_that_writes_after_its_run_was_taken(incident_id: str) -> None:
        with connect_from_env() as walking:
            fence(walking, holding.current())
            _the_run_taken_from_under_it(incident_id)
            _a_write_on(walking, incident_id)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, dont_care_alert, at=utc_now())
        incidents.transition(conn, incident_id, IncidentStatus.MITIGATING, at=utc_now())
        runs.enqueue(conn, incident_id)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: worker.take_one_run(
                    conn,
                    some_worker,
                    A_GENEROUS_LEASE,
                    walk=walk_that_writes_after_its_run_was_taken,
                    unwind=_an_unwind_recording_what_it_was_given(unwound),
                    ended_by_a_person=ended_by_a_person_via(connect_from_env),
                    holding=holding
                )
            ) \
            .then(all_of(
                _nothing_was_put_back(unwound),
                _the_run_is_held_by(conn, incident_id, THE_WORKER_THAT_TOOK_IT_BACK),
                _the_incident_is(conn, incident_id, IncidentStatus.MITIGATING),
                one_record_was_logged(caplog, THE_WORKER, logging.WARNING,
                                      "run lost, leaving it to whoever holds it now"),
                _it_was_never_logged(caplog, "run failed")
            ))


def _a_connection_named(application: str) -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, application_name=application)


def _a_write_on(conn: psycopg.Connection, incident_id: str) -> None:
    conn.execute("UPDATE incident SET status = status WHERE id = %s", (incident_id,))
    conn.commit()


def _held_while_worked_and_not_after(conn: psycopg.Connection,
                                     incident_id: str,
                                     held_during: list[Fence | None],
                                     holding: Holding,
                                     times_asked: int) -> Assertion[bool]:
    """The run as its claim holds it, each time the walk or the unwind looked,
    and nothing once the run was over."""
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)
        expected = [None if run is None else Fence(run_id=run.id, epoch=run.epoch)] * times_asked
        held_after = holding.current()

        if held_during != expected or held_after is not None:
            raise AssertionError(
                f"Expected the run held as {expected} while it was worked and nothing "
                f"after; held {held_during} during and [{held_after}] after."
            )

        return True

    return assertion


def _the_write_after_it_was_refused_as(sqlstate: str) -> Assertion[Any]:
    def assertion(took_work_then_refused: Any) -> bool:
        _, refused = took_work_then_refused
        found = refused.sqlstate if isinstance(refused, psycopg.Error) else None

        if found != sqlstate:
            raise AssertionError(
                f"Expected a write on the worker's connection after its run refused as "
                f"[{sqlstate}], got [{found}] from "
                f"[{None if refused is None else f'{type(refused).__name__}: {refused}'}]."
            )

        return True

    return assertion


def _an_action_claimed_on_its_own_connection(incident_id: str) -> None:
    with connect_from_env() as conn:
        _an_action_claimed_on(conn, incident_id)


def _the_run_taken_from_under_it(incident_id: str) -> None:
    """The run's lease run out while its holder was paused, and the run taken
    back by another worker."""
    with connect_from_env() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE incident_run SET leased_until = now() - interval '1 second' "
                           "WHERE incident_id = %s", (incident_id,))
        conn.commit()

        claimed = runs.claim(conn, THE_WORKER_THAT_TOOK_IT_BACK, A_GENEROUS_LEASE)
        assert claimed is not None


def _nothing_was_put_back(unwound: list[str]) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if unwound:
            raise AssertionError(f"Expected nothing put back, got {unwound}.")

        return True

    return assertion


def _an_unwind_told_its_run_was_lost() -> Callable[[str], None]:
    def unwind(dont_care_incident_id: str) -> None:
        raise RunLost("a newer claim holds this run")

    return unwind


def _the_run_is_held_by(conn: psycopg.Connection,
                        incident_id: str,
                        holder: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)

        if run is None or run.state != runs.RunState.RUNNING or run.claimed_by != holder:
            raise AssertionError(
                f"Expected the run still running, held by [{holder}], got "
                f"[{None if run is None else (run.state, run.claimed_by)}]."
            )

        return True

    return assertion


def _the_incident_was_not_escalated(conn: psycopg.Connection,
                                    incident_id: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None or incident.status is IncidentStatus.ESCALATED:
            raise AssertionError(
                f"Expected a lost run's incident not to be escalated, got "
                f"[{None if incident is None else incident.status}]."
            )

        return True

    return assertion


def _it_was_never_logged(caplog: pytest.LogCaptureFixture, message: str) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if any(record.getMessage() == message for record in caplog.records):
            raise AssertionError(f"Expected a lost run never to log [{message}], and it did.")

        return True

    return assertion


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


def _the_incident_is(conn: psycopg.Connection,
                     incident_id: str,
                     expected: IncidentStatus) -> Assertion[bool]:
    """The status a person reading the incident would see.

    Stated positively, unlike `_the_incident_was_not_called_resolved` beside it.
    That one rules out the single wrong answer a resolved incident would be, and
    passes for every status including the one this exists to refuse - an
    incident left in the phase its walk died in.
    """
    def assertion(_took_work: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != expected:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be [{expected}], and it "
                f"is [{incident.status}] - so a walk that stopped without "
                f"finishing has left it reading as work in progress that "
                f"nothing is going to pick up."
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


def _an_action_claimed_on(conn: psycopg.Connection, incident_id: str) -> None:
    """A claim on a candidate of the incident's, written by the real writer and
    answered by nothing - what a walk leaves when it stops mid-action."""
    candidate = a_determined_hypothesis(incident_id)
    hypotheses.record(conn, candidate)
    taken_actions.claim(conn, incident_id, hypothesis_id=candidate.id,
                        action_type=REVERT_FEATURE_FLAG, subject="dont-care-flag",
                        at=utc_now())


def _a_walk_that_claims_an_action_and_fails(
    failing_with: Exception | None = None
) -> Callable[[str], None]:
    """A walk that stopped mid-action the way an unforeseen failure stops one -
    or as `failing_with` stops it: its claim written, and nothing after it."""
    def walk(incident_id: str) -> None:
        with connect_from_env() as conn:
            _an_action_claimed_on(conn, incident_id)

        raise failing_with if failing_with is not None else RuntimeError("dont care")

    return walk


def _requeued_before(conn: psycopg.Connection, incident_id: str, retries: int) -> None:
    """The incident's run as one already requeued `retries` times."""
    conn.execute("UPDATE incident_run SET retries = %s WHERE incident_id = %s",
                 (retries, incident_id))
    conn.commit()


def _the_run_waits_to_be_tried_again(conn: psycopg.Connection,
                                     incident_id: str,
                                     retries: int) -> Assertion[bool]:
    """Back in line after being requeued `retries` times, held by nobody, and not
    to be taken yet."""
    def assertion(_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)
        found = None if run is None else (run.state, run.retries, run.claimed_by)
        waiting = run is not None and run.not_before is not None and run.not_before > utc_now()

        if found != (runs.RunState.QUEUED, retries, None) or not waiting:
            raise AssertionError(
                f"Expected the run queued again after [{retries}] retries, held by nobody and "
                f"waiting, got (state, retries, holder) [{found}] waiting until "
                f"[{None if run is None else run.not_before}]."
            )

        return True

    return assertion


def _the_run_waits_about(conn: psycopg.Connection,
                         incident_id: str,
                         wait: timedelta) -> Assertion[bool]:
    """Not to be taken for `wait` from the moment it was requeued, as the
    database's own clock reads it - give or take the moments this test took."""
    def assertion(_took_work: bool) -> bool:
        with conn.cursor() as cursor:
            cursor.execute("SELECT not_before - now() FROM incident_run WHERE incident_id = %s",
                           (incident_id,))
            row = cursor.fetchone()

        left = None if row is None else row[0]

        if left is None or not wait - A_MOMENT_THE_TEST_TAKES < left <= wait:
            raise AssertionError(
                f"Expected the run requeued for [{wait}], and it has [{left}] left to wait."
            )

        return True

    return assertion


def _its_actions_are_seen_as(incident_id: str,
                             expected: list[ActionProgress]) -> Assertion[bool]:
    """How far each of the incident's actions got, as a connection of its own
    reads them - which only a committed settling shows."""
    def assertion(_took_work: bool) -> bool:
        with connect_from_env() as conn:
            seen = [taken.progress for taken in taken_actions.get_by_incident(conn, incident_id)]

        if seen != expected:
            raise AssertionError(f"Expected the incident's actions seen as {expected}, "
                                 f"got {seen}.")

        return True

    return assertion


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


def _nothing_was_unwound(unwound: list[str]) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        if unwound:
            raise AssertionError(
                f"Expected nothing to be put back for an incident a person "
                f"resolved, got {unwound}."
            )

        return True

    return assertion


def _connections_only_before_the_walk() -> Connections:
    """Connections to the database until the walk starts, and none after -
    the first one opened is the worker's read of the incident it claimed."""
    opened: list[bool] = []

    def connections() -> psycopg.Connection:
        if opened:
            raise ConnectionError("the database went away")

        opened.append(True)

        return connect_from_env()

    return connections


def _readable_only_before_the_walk() -> EndedByAPerson:
    """Nobody's ending when the run is claimed, and unreadable after."""
    asked: list[str] = []

    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        asked.append(incident_id)

        if len(asked) > 1:
            raise RuntimeError("the database went away")

        return None

    return ended_by_a_person


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


def _the_run_continued_the_trace_its_incident_kept(observed: Observed,
                                                    conn: psycopg.Connection,
                                                    incident_id: str) -> Assertion[bool]:
    def assertion(dont_care_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)
        worked = [span for span in observed.spans() if span.name == "run"]
        said = [
            (
                (f"{span.parent.trace_id:032x}", f"{span.parent.span_id:016x}")
                if span.parent is not None else None,
                (span.attributes or {}).get(ARGUS_INCIDENT_ID),
                (span.attributes or {}).get(ARGUS_RUN_ID)
            )
            for span in worked
        ]
        expected = [((SOME_TRACE, SOME_SPAN), incident_id, run.id if run else None)]

        if said != expected:
            raise AssertionError(
                f"Expected one [run] span continuing the trace the incident kept, "
                f"naming the incident and the run, {expected}; the run spans were "
                f"{said}."
            )

        return True

    return assertion


def _the_walk_saw_its_incident_and_run(seen: list[dict[str, object]],
                                       conn: psycopg.Connection,
                                       incident_id: str) -> Assertion[bool]:
    def assertion(dont_care_took_work: bool) -> bool:
        run = runs.get_run_for_incident(conn, incident_id)
        expected = {ARGUS_INCIDENT_ID: incident_id, ARGUS_RUN_ID: run.id if run else None}
        saw = [
            {key: carried.get(key) for key in (ARGUS_INCIDENT_ID, ARGUS_RUN_ID)}
            for carried in seen
        ]

        if saw != [expected]:
            raise AssertionError(
                f"Expected the walk to run once with {expected} in the baggage, "
                f"and it saw {saw}."
            )

        return True

    return assertion


def _the_walk_found_no_transaction_open(seen: list[TransactionStatus]) -> Assertion[bool]:
    def assertion(dont_care_took_work: bool) -> bool:
        if seen != [TransactionStatus.IDLE]:
            raise AssertionError(
                f"Expected the walk to run once with nothing open on the worker's "
                f"connection, and it found it {[status.name for status in seen]}."
            )

        return True

    return assertion


def _it_ended_when_the_account_says_it_was(conn: psycopg.Connection,
                                           incident_id: str,
                                           status: IncidentStatus) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        said_at = [event.at for event in events.get_by_incident(conn, incident_id)
                   if isinstance(event, StatusChanged) and event.to_status == status]
        incident = incidents.get(conn, incident_id)
        ended_at = incident.ended_at if incident is not None else None

        if said_at != [ended_at]:
            raise AssertionError(
                f"Expected the incident to end at the moment its account says it was "
                f"[{status}], it ended at [{ended_at}] and was said to at {said_at}."
            )

        return True

    return assertion


def _the_account_never_said_it_was(conn: psycopg.Connection,
                                   incident_id: str,
                                   status: IncidentStatus) -> Assertion[bool]:
    def assertion(_took_work: bool) -> bool:
        moves = [event.to_status
                 for event in events.get_by_incident(conn, incident_id)
                 if isinstance(event, StatusChanged)]

        if status in moves:
            raise AssertionError(
                f"Expected the account to say nothing about a move to [{status}] "
                f"the incident never made, got {moves}."
            )

        return True

    return assertion
