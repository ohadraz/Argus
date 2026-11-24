from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final

import psycopg
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
    the_answer_was,
)
from core import utc_now
from core.models import ALERT_FIRING, Alert, Incident, IncidentStanding, IncidentStatus, Reference
from core.stored import ALERT, SHIPPED, NewerShape, Shapes
from core.telemetry import ARGUS_INCIDENT_ID
from incident_record.repository import incidents, references
from postgres import connect_from_env

from incident_record_test.framework import no_column_is_empty, written_and_rolled_back
from incident_record_test.framework.builders import (
    an_incident_created_for,
    an_incident_whose_alert_cannot_be_read,
)

# The logger the incident repository writes to, and what it says of a row a
# list passed over.
THE_REPOSITORY: Final = "incident_record.repository.incidents"
PASSED_OVER: Final = "incident passed over: its row cannot be read"

# What a step from an alert's shape to the next one writes, where no release
# has shipped a step: a value no alert here is written with, so an alert
# carrying it was brought up through the step and not read as it was stored.
SOME_SUMMARY_A_STEP_WROTE = "written by the step to the next shape"


@pytest.mark.integration
def test_create_writes_the_incident_acknowledged() -> None:
    # `acknowledged`, not `investigating`: this runs where the alert is
    # received, and the walk it queues belongs to a worker that has not taken
    # it yet. The line saying the alert arrived is published by the intake
    # beside this, and asserted there.
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .when(
                lambda: incidents.create(conn, some_alert, at=utc_now())
            ) \
            .then(
                the_incident_is("acknowledged")
            )


@pytest.mark.integration
def test_an_incident_opens_at_the_moment_it_is_given() -> None:
    # The moment of the line opening its account. Stamped by the database's own
    # clock instead, the row and the account disagree about when it began.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_moment = datetime(2026, 10, 21, 19, 12, 56, 123456, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_opened_at = partial(_the_incident_opened_at, conn)

        Scenario() \
            .when(
                lambda: incidents.create(conn, some_alert, at=some_moment)
            ) \
            .then(
                the_incident_opened_at(some_moment)
            )


@pytest.mark.integration
def test_transition_updates_the_status() -> None:
    # The whole of what this writes. What moved the incident, why, and how sure
    # it was are published as the `StatusChanged` beside it, on the same
    # connection - asserted where that is published rather than here, because
    # here there is nothing left to hold them.
    some_service = "buki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn, incident_id, IncidentStatus.MITIGATING,
                    at=utc_now()
                )
            ) \
            .then(
                the_incident_is("mitigating", incident_id=incident_id)
            )


@pytest.mark.integration
def test_get_current_prefers_an_incident_that_has_not_finished() -> None:
    # Not simply the newest. An incident that resolved after this one opened has
    # nothing left to watch; the one still running is what a reader came for.
    with connect_from_env() as conn:
        # Created first, so it is also the *older* of the two - which is what
        # makes this a claim about "has not finished" rather than about "newest".
        still_running = incidents.create(
            conn, Alert(service="running", alert_name="HighErrorRate"),
            at=utc_now()
        )
        already_finished = incidents.create(
            conn, Alert(service="finished", alert_name="HighErrorRate"),
            at=utc_now()
        )
        incidents.transition(conn, already_finished, IncidentStatus.RESOLVED, at=utc_now())

        Scenario() \
            .given(
                still_running
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _the_current_incident_was(still_running)
            )


@pytest.mark.integration
def test_get_current_falls_back_to_the_newest_when_nothing_is_running() -> None:
    # A resolved incident vanishing the moment it resolves would take it off the
    # screen exactly when everyone is looking at it.
    with connect_from_env() as conn:
        _no_incidents_at_all(conn)

        the_only_one_there_has_been = incidents.create(
            conn, Alert(service="io-shop", alert_name="HighErrorRate"),
            at=utc_now()
        )
        incidents.transition(conn, the_only_one_there_has_been, IncidentStatus.RESOLVED,
                             at=utc_now())

        Scenario() \
            .given(
                the_only_one_there_has_been
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _the_current_incident_was(the_only_one_there_has_been)
            )


@pytest.mark.integration
def test_get_current_is_none_when_there_has_never_been_an_incident() -> None:
    # The state Argus is in most of the time, and the one the front page has to
    # say out loud rather than render as an empty frame.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                calling(lambda: _no_incidents_at_all(conn))
            ) \
            .when(
                lambda: incidents.get_current(conn)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_that_resolved_records_when_it_ended() -> None:
    # How long an incident lasted is a figure the postmortem reports, so it is
    # recorded when it happens rather than inferred later from whichever row
    # was written last - an inference that changes silently the moment
    # anything is logged late.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.RESOLVED,
                    at=utc_now(),
                )
            ) \
            .then(
                the_incident_records_an_end(incident_id)
            )


@pytest.mark.integration
def test_an_incident_that_escalated_records_when_it_ended() -> None:
    # Escalation is an ending too. An incident nobody could resolve still cost
    # what it cost, and a postmortem that could not say how long it ran would
    # be missing the figure for exactly the incidents that ran longest.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.ESCALATED,
                    at=utc_now(),
                )
            ) \
            .then(
                the_incident_records_an_end(incident_id)
            )


@pytest.mark.integration
def test_a_move_that_ends_an_incident_ends_it_at_the_moment_given() -> None:
    # The moment of the line saying so: the summary said Argus stopped at
    # 19:14:02, the database's transaction start, a second before that line.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_moment = datetime(2026, 10, 21, 19, 14, 3, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_ended_at = partial(_the_incident_ended_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.ESCALATED,
                                             at=some_moment)
            ) \
            .then(
                the_incident_ended_at(incident_id, some_moment)
            )


@pytest.mark.integration
def test_a_withdrawal_ends_an_incident_at_the_moment_given() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_moment = datetime(2026, 10, 21, 19, 14, 3, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_ended_at = partial(_the_incident_ended_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, at=some_moment)
            ) \
            .then(
                the_incident_ended_at(incident_id, some_moment)
            )


@pytest.mark.integration
def test_a_resolution_ends_a_running_incident_at_the_moment_given() -> None:
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    some_moment = datetime(2026, 10, 21, 19, 14, 3, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_ended_at = partial(_the_incident_ended_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.resolve(conn, incident_id, at=some_moment)
            ) \
            .then(
                the_incident_ended_at(incident_id, some_moment)
            )


@pytest.mark.integration
def test_an_incident_still_being_worked_records_no_end() -> None:
    # `fixing` is the case worth stating: it reads like an ending and is not
    # one - Code-Fix is still looking - so an incident stamped on the way into
    # it would report a duration for something still running.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_records_no_end = partial(_the_incident_records_no_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(
                    conn,
                    incident_id,
                    IncidentStatus.FIXING,
                    at=utc_now(),
                )
            ) \
            .then(
                the_incident_records_no_end(incident_id)
            )


@pytest.mark.integration
def test_a_move_back_to_work_clears_the_end_an_earlier_move_stamped() -> None:
    # A step run again from its checkpoint can take a different road than its
    # interrupted attempt: the first found the alarm disproven, and the second,
    # asking the model again, goes on to mitigate. An incident still being
    # worked must not carry the end the first attempt wrote.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_first_attempts_moment = datetime(2026, 10, 21, 19, 14, 3, 456789, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_records_no_end = partial(_the_incident_records_no_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert),
                calling(lambda: incidents.transition(conn, incident_id,
                                                     IncidentStatus.DISPROVEN,
                                                     at=the_first_attempts_moment))
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.MITIGATING,
                                             at=utc_now())
            ) \
            .then(
                the_incident_records_no_end(incident_id)
            )


@pytest.mark.integration
def test_an_incident_ended_again_after_a_move_back_to_work_ends_at_the_last_moment() -> None:
    # The end the row says is the one the account's last move says: the first
    # attempt's end was taken back with its line, and the move that ends the
    # incident now is the one a duration is measured to.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    the_first_attempts_moment = datetime(2026, 10, 21, 19, 14, 3, 456789, tzinfo=UTC)
    the_last_moment = datetime(2026, 10, 21, 19, 22, 41, 123456, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_ended_at = partial(_the_incident_ended_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert),
                calling(lambda: incidents.transition(conn, incident_id,
                                                     IncidentStatus.DISPROVEN,
                                                     at=the_first_attempts_moment)),
                calling(lambda: incidents.transition(conn, incident_id,
                                                     IncidentStatus.MITIGATING,
                                                     at=utc_now()))
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.ESCALATED,
                                             at=the_last_moment)
            ) \
            .then(
                the_incident_ended_at(incident_id, the_last_moment)
            )


@pytest.mark.integration
def test_transition_says_that_it_took_effect() -> None:
    # The walk publishes a move and carries on only where the row actually
    # moved, so a transition that wrote nothing must not read the same as one
    # that did.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.MITIGATING,
                                             at=utc_now())
            ) \
            .then(
                _the_transition_reported(True)
            )


@pytest.mark.integration
@pytest.mark.parametrize("to_status", [status for status in IncidentStatus
                                       if status is not IncidentStatus.WITHDRAWN])
def test_a_withdrawn_incident_is_not_moved_by_a_transition(to_status: IncidentStatus) -> None:
    # A person withdrew it while a step of the walk was still running. The step
    # finishing afterwards must not write over that decision - which is how a
    # withdrawn incident went back to `mitigating` and was never put back.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_withdrawn_incident_for = partial(_a_withdrawn_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := a_withdrawn_incident_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, to_status, at=utc_now())
            ) \
            .then(all_of(
                _the_transition_reported(False),
                the_incident_is(IncidentStatus.WITHDRAWN, incident_id=incident_id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("to_status", [status for status in IncidentStatus
                                       if status is not IncidentStatus.RESOLVED])
def test_a_resolved_incident_is_not_moved_by_a_transition(to_status: IncidentStatus) -> None:
    # A person reported it resolved while a step of the walk was still running.
    # Their report is the fact, so the step finishing afterwards must not write
    # its own status over it - nor may the worker's `escalated` on a walk that
    # failed after the report.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_resolved_incident_for = partial(_a_resolved_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := a_resolved_incident_for(some_alert)
            ) \
            .when(
                lambda: incidents.transition(conn, incident_id, to_status, at=utc_now())
            ) \
            .then(all_of(
                _the_transition_reported(False),
                the_incident_is(IncidentStatus.RESOLVED, incident_id=incident_id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("status", [status for status in IncidentStatus
                                    if not status.is_terminal()])
def test_an_incident_still_being_worked_is_escalated_when_its_walk_stopped(
    status: IncidentStatus
) -> None:
    # The walk raised part-way through, and nothing will take its run again. An
    # incident left where the walk was - `mitigating`, most often - reads as
    # work in progress that nobody is going to pick up.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_moment = datetime(2026, 10, 28, 3, 50, 1, 234567, tzinfo=UTC)

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_ended_at = partial(_the_incident_ended_at, conn)

        Scenario() \
            .given(
                incident_id := _an_incident_at(conn, some_alert, status)
            ) \
            .when(
                lambda: incidents.escalate_unless_ended(conn, incident_id, at=some_moment)
            ) \
            .then(all_of(
                _the_transition_reported(True),
                the_incident_is(IncidentStatus.ESCALATED, incident_id=incident_id),
                the_incident_ended_at(incident_id, some_moment)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("ending", [status for status in IncidentStatus if status.is_terminal()])
def test_an_incident_that_already_ended_is_not_escalated_when_its_walk_stopped(
    ending: IncidentStatus
) -> None:
    # The walk failed after an ending - its own, in the write-up after it
    # mitigated, or a person's. Escalating would call a mitigated incident one
    # a person must take over, and re-stamp when it ended. In the statement
    # rather than a read before it, as `transition` keeps a person's endings:
    # a read that failed would otherwise leave a stopped walk unescalated.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_still_ended_at = partial(_the_incident_still_ended_at, conn)

        Scenario() \
            .given(
                incident_id := _an_incident_ended_as(conn, some_alert, ending),
                ended_at := _when_it_ended(conn, incident_id)
            ) \
            .when(
                lambda: incidents.escalate_unless_ended(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _the_transition_reported(False),
                the_incident_is(ending, incident_id=incident_id),
                the_incident_still_ended_at(incident_id, ended_at)
            ))


@pytest.mark.integration
def test_incidents_come_back_newest_first() -> None:
    # The history view opens on what just happened. Oldest-first would put the
    # incident somebody is looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name="HighErrorRate")
    a_newer_alert = Alert(service="newer-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incidents_come_back = partial(_the_incidents_come_back, conn)

        older = an_incident_created_for(conn, an_older_alert)
        # `now()` is transaction time, so two incidents created in one
        # transaction share a timestamp and the ordering has nothing left to
        # break the tie - which is not how an incident is ever created.
        conn.commit()
        newer = an_incident_created_for(conn, a_newer_alert)

        Scenario() \
            .given(
                older, newer
            ) \
            .when(
                lambda: incidents.get_recent(conn)
            ) \
            .then(
                the_incidents_come_back(newest=newer, before=older)
            )


@pytest.mark.integration
def test_a_running_incident_can_be_withdrawn() -> None:
    # Withdrawal is the one status set from outside the walk. Everything else
    # an incident becomes is derived from work the walk did and written by the
    # walk itself; this is written by whoever pressed the button.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                the_incident_is(IncidentStatus.WITHDRAWN, incident_id=incident_id),
                the_incident_records_an_end(incident_id)
            ))


@pytest.mark.integration
def test_withdrawing_says_that_it_took_effect() -> None:
    # The answer is what the endpoint reports back and what the walk's own
    # unwind is conditioned on, so a withdrawal that silently did nothing must
    # not read the same as one that stopped an incident.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .then(
                _it_reported(True)
            )


@pytest.mark.integration
def test_an_incident_that_already_ended_is_not_withdrawn() -> None:
    # A resolved incident was resolved by a mitigation that is holding the
    # service up. Withdrawing it would put the failure back.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_resolved_incident_for = partial(_a_resolved_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := a_resolved_incident_for(some_alert)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(IncidentStatus.RESOLVED, incident_id=incident_id)
            ))


@pytest.mark.integration
def test_withdrawing_twice_changes_nothing_the_second_time() -> None:
    # The page can be double-clicked and a teardown can withdraw what a case
    # already withdrew. Neither should write a second row, and neither should
    # move the end time the first one stamped.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_withdrawn_incident_for = partial(_a_withdrawn_incident_for, conn)
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_still_ended_at = partial(_the_incident_still_ended_at, conn)

        incident_id = a_withdrawn_incident_for(some_alert)

        Scenario() \
            .given(
                first_ended_at := _when_it_ended(conn, incident_id)
            ) \
            .when(
                lambda: incidents.withdraw(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _it_reported(False),
                the_incident_is(IncidentStatus.WITHDRAWN, incident_id=incident_id),
                the_incident_still_ended_at(incident_id, first_ended_at)
            ))


@pytest.mark.integration
def test_a_running_incident_can_be_resolved() -> None:
    # A person reported it over. Their report is the fact, so the incident
    # ends at the moment they said so.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_records_an_end = partial(_the_incident_records_an_end, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.resolve(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _the_resolution_reported(True),
                the_incident_is(IncidentStatus.RESOLVED, incident_id=incident_id),
                the_incident_records_an_end(incident_id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("ending", [IncidentStatus.MITIGATED,
                                    IncidentStatus.ESCALATED,
                                    IncidentStatus.RECOMMENDED])
def test_resolving_an_incident_argus_had_ended_keeps_its_end(ending: IncidentStatus) -> None:
    # Argus stopped, somebody carried on, and later reported it resolved. The
    # postmortem was written to the end Argus reached and is not rewritten, so
    # an end restamped here would put it out of step with its own durations.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)
        the_incident_still_ended_at = partial(_the_incident_still_ended_at, conn)

        incident_id = _an_incident_ended_as(conn, some_alert, ending)

        Scenario() \
            .given(
                argus_ended_it_at := _when_it_ended(conn, incident_id)
            ) \
            .when(
                lambda: incidents.resolve(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _the_resolution_reported(True),
                the_incident_is(IncidentStatus.RESOLVED, incident_id=incident_id),
                the_incident_still_ended_at(incident_id, argus_ended_it_at)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED,
                                    IncidentStatus.WITHDRAWN,
                                    IncidentStatus.DISPROVEN])
def test_an_incident_a_resolution_would_contradict_is_not_resolved(ending: IncidentStatus) -> None:
    # Resolved already is; withdrawn had its changes put back on a person's
    # say-so; disproven had no incident to resolve.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        the_incident_is = partial(_the_incident_is, conn)

        Scenario() \
            .given(
                incident_id := _an_incident_ended_as(conn, some_alert, ending)
            ) \
            .when(
                lambda: incidents.resolve(conn, incident_id, at=utc_now())
            ) \
            .then(all_of(
                _the_resolution_reported(False),
                the_incident_is(ending, incident_id=incident_id)
            ))


def _no_incidents_at_all(conn: psycopg.Connection) -> None:
    """An empty table, which is the one state "the newest incident" cannot be
    set up into by adding a row."""
    with conn.cursor() as cursor:
        cursor.execute("TRUNCATE incident CASCADE")
    conn.commit()


@pytest.mark.integration
def test_get_returns_none_for_unknown_incident() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                an_id_no_incident_was_ever_given := "00000000-0000-0000-0000-000000000000"
            ) \
            .when(
                lambda: incidents.get(conn, an_id_no_incident_was_ever_given)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_that_ended_leaves_no_column_of_its_row_empty() -> None:
    # Two writes, because no single one fills this row: the insert opens the
    # incident and the transition that ends it stamps when. Together they are
    # the complete life of an incident, and what comes of it is what every
    # reader of the table sees. An alert naming its rule, since one naming none
    # leaves the rule's column empty by right.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", rule="some-rule")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

        Scenario() \
            .when(
                lambda: incidents.transition(conn, incident_id, IncidentStatus.RESOLVED,
                                             at=utc_now())
            ) \
            .then(
                no_column_is_empty(conn, "incident", "id", incident_id)
            )


@pytest.mark.integration
def test_an_open_incident_is_found_by_the_rule_and_service_that_opened_it() -> None:
    # What a rule firing again while Argus is still on its incident joins.
    some_rule = "some-rule"
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule=some_rule)

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _it_found(incident_id)
            )


@pytest.mark.integration
@pytest.mark.parametrize("ending", [status for status in IncidentStatus if status.is_terminal()])
def test_an_incident_that_ended_is_not_found_open(ending: IncidentStatus) -> None:
    # Once it is over, the rule firing again is a new incident - whichever way
    # it ended.
    some_rule = "some-rule"
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule=some_rule)

    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: incidents.transition(conn, incident_id, ending, at=utc_now()))
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_of_two_open_incidents_from_one_rule_the_newer_is_found() -> None:
    # Two open at once is two deliveries of one alert that raced each other in.
    # One answer either way, and it is the newer.
    some_rule = "some-rule"
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule=some_rule)

    with connect_from_env() as conn:
        older = an_incident_created_for(conn, some_alert)
        # `now()` is transaction time, so two incidents created in one
        # transaction share a timestamp and nothing is left to break the tie.
        conn.commit()
        newer = an_incident_created_for(conn, some_alert)

        Scenario() \
            .given(
                older, newer
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _it_found(newer)
            )


@pytest.mark.integration
def test_another_rules_open_incident_is_not_found() -> None:
    some_rule = "some-rule"
    some_other_rule = "some-other-rule"
    some_service = "kuki-service"
    an_alert_from_another_rule = Alert(
        service=some_service, alert_name="HighErrorRate", rule=some_other_rule
    )

    with connect_from_env() as conn:
        Scenario() \
            .given(
                an_incident_created_for(conn, an_alert_from_another_rule)
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_the_same_rules_open_incident_for_another_service_is_not_found() -> None:
    # A rule watching several services pages for each one, and each is an
    # incident of its own: the service paged for is what Argus investigates.
    some_rule = "some-rule"
    some_service = "kuki-service"
    some_other_service = "buki-service"
    an_alert_for_another_service = Alert(
        service=some_other_service, alert_name="HighErrorRate", rule=some_rule
    )

    with connect_from_env() as conn:
        Scenario() \
            .given(
                an_incident_created_for(conn, an_alert_for_another_service)
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
@pytest.mark.parametrize("status", list(IncidentStatus))
def test_an_incident_is_found_by_a_name_it_holds_for_its_service(status: IncidentStatus) -> None:
    # What a reminder of a firing joins: the incident the firing opened,
    # however it ended. Whether its ending lets the reminder join is intake's
    # to decide, so every status is found here.
    some_service = "kuki-service"
    some_firing = _a_firing("fp-1@2026-10-14T15:59:00Z")

    with connect_from_env() as conn:
        incident_id = _an_incident_holding(conn, some_service, some_firing)

        Scenario() \
            .given(
                calling(lambda: _it_ended_as(conn, incident_id, status))
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, ["fp-unknown", some_firing.value], some_service
                )
            ) \
            .then(
                _it_found(incident_id)
            )


@pytest.mark.integration
def test_of_two_incidents_holding_a_name_the_newer_is_found() -> None:
    # A firing reminded of after a mitigation is held by the incident it
    # opened and by the one its reminder opened. The newer is the latest word
    # about it.
    some_service = "kuki-service"
    some_firing = _a_firing("fp-1@2026-10-14T15:59:00Z")

    with connect_from_env() as conn:
        older = _an_incident_holding(conn, some_service, some_firing)
        # `now()` is transaction time, so two incidents created in one
        # transaction share a timestamp and nothing is left to break the tie.
        conn.commit()
        newer = _an_incident_holding(conn, some_service, some_firing)

        Scenario() \
            .given(
                older, newer
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, [some_firing.value], some_service
                )
            ) \
            .then(
                _it_found(newer)
            )


@pytest.mark.integration
def test_another_services_incident_holding_the_name_is_not_found() -> None:
    # One alert group spans every service its rule watches, and a notification
    # carries every firing in it - so an incident holds firings that are not
    # its own service's.
    some_service = "kuki-service"
    some_firing = _a_firing("fp-1@2026-10-14T15:59:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_incident_holding(conn, "buki-service", some_firing)
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, [some_firing.value], some_service
                )
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_holding_the_value_as_another_kind_is_not_found() -> None:
    some_service = "kuki-service"
    some_value = "fp-1@2026-10-14T15:59:00Z"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_incident_holding(conn, some_service, Reference(
                    source="some-monitor", kind="some-other-kind", value=some_value
                ))
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, [some_value], some_service
                )
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_a_name_no_incident_holds_finds_nothing() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                _an_incident_holding(conn, "kuki-service",
                                     _a_firing("fp-1@2026-10-14T15:59:00Z"))
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, ["fp-2@2026-10-14T17:20:00Z"], "kuki-service"
                )
            ) \
            .then(
                _nothing_came_back()
            )


@pytest.mark.integration
def test_an_incident_is_read_back_with_the_alert_it_was_opened_for() -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate", rule="some-rule",
                       summary="5xx above 5% for 2 minutes")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.get(conn, incident_id)
            ) \
            .then(
                _its_alert_is(some_alert)
            )


@pytest.mark.integration
def test_an_incident_written_in_an_older_shape_is_brought_up_before_it_is_read() -> None:
    # Read with the shapes of a release one step on: the row is at the shape
    # this release writes, which that release reads as one step behind.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    one_step_on = Shapes(upcasters={ALERT: [_a_step_writing_the_summary]})

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .when(
                lambda: incidents.get(conn, incident_id, one_step_on)
            ) \
            .then(
                _its_alert_is(some_alert.model_copy(update={"summary": SOME_SUMMARY_A_STEP_WROTE}))
            )


@pytest.mark.integration
def test_an_incident_written_by_a_newer_argus_is_not_read_as_this_one() -> None:
    # Read as the shape this release knows, whatever the newer one moved would
    # sit in the wrong field. One incident asked for by name is not passed
    # over, either: a page or a postmortem made of part of it would be wrong.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_written_by_a_newer_argus(conn, dont_care_alert)
            ) \
            .when(
                attempting(lambda: incidents.get(conn, incident_id))
            ) \
            .then(
                an_error_was_raised(NewerShape)
            )


@pytest.mark.integration
def test_an_incident_whose_alert_cannot_be_read_is_passed_over_in_the_list(
    caplog: pytest.LogCaptureFixture
) -> None:
    # One bad row would otherwise take every incident there has ever been off
    # the history page.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        readable = an_incident_created_for(conn, some_alert)
        unreadable = an_incident_whose_alert_cannot_be_read(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.WARNING, logger=THE_REPOSITORY))
            ) \
            .when(
                lambda: incidents.get_recent(conn)
            ) \
            .then(all_of(
                _the_incidents_listed_are([readable]),
                one_record_was_logged(caplog, THE_REPOSITORY, logging.WARNING, PASSED_OVER,
                                      {ARGUS_INCIDENT_ID: unreadable, "newer": False})
            ))


@pytest.mark.integration
def test_an_incident_written_by_a_newer_argus_is_passed_over_in_the_list(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Said as newer, so a reader of the log knows a release that knows its
    # shape would list it, where one that cannot be read is nobody's to list.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        readable = an_incident_created_for(conn, some_alert)
        newer = _an_incident_written_by_a_newer_argus(conn, some_alert)

        Scenario() \
            .given(
                calling(lambda: caplog.set_level(logging.WARNING, logger=THE_REPOSITORY))
            ) \
            .when(
                lambda: incidents.get_recent(conn)
            ) \
            .then(all_of(
                _the_incidents_listed_are([readable]),
                one_record_was_logged(caplog, THE_REPOSITORY, logging.WARNING, PASSED_OVER,
                                      {ARGUS_INCIDENT_ID: newer, "newer": True})
            ))


@pytest.mark.integration
def test_an_open_incident_whose_alert_cannot_be_read_is_still_found_by_its_rule() -> None:
    # The lookup decides by the rule and service, which are not the stored
    # alert. Parsing it anyway, one incident whose alert cannot be read would
    # stop every later firing of its rule from being taken in.
    some_rule = "some-rule"
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate", rule=some_rule)

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_whose_alert_cannot_be_read(conn, some_alert)
            ) \
            .when(
                lambda: incidents.get_open_by_rule_and_service(conn, some_rule, some_service)
            ) \
            .then(
                _it_found(incident_id)
            )


@pytest.mark.integration
def test_an_incident_whose_alert_cannot_be_read_is_still_found_by_a_name_it_holds() -> None:
    some_service = "kuki-service"
    some_firing = _a_firing("fp-1@2026-10-14T15:59:00Z")

    with connect_from_env() as conn:
        incident_id = an_incident_whose_alert_cannot_be_read(
            conn, Alert(service=some_service, alert_name="HighErrorRate")
        )

        Scenario() \
            .given(
                calling(lambda: references.add(conn, incident_id, [some_firing]))
            ) \
            .when(
                lambda: incidents.get_newest_by_names_and_service(
                    conn, ALERT_FIRING, [some_firing.value], some_service
                )
            ) \
            .then(
                _it_found(incident_id)
            )


@pytest.mark.integration
def test_a_withdrawal_rolled_back_by_its_caller_leaves_the_incident_as_it_was() -> None:
    # Committing is the caller's. A withdrawal that committed on its own would
    # stand after its caller rolled back: an incident ended, and no account of
    # it saying so.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert),
                as_it_was := incidents.get(conn, incident_id),
                calling(written_and_rolled_back(
                    conn, lambda: incidents.withdraw(conn, incident_id, at=utc_now())
                ))
            ) \
            .when(
                lambda: incidents.get(conn, incident_id)
            ) \
            .then(
                the_answer_was(as_it_was)
            )


@pytest.mark.integration
def test_a_resolution_rolled_back_by_its_caller_leaves_the_incident_as_it_was() -> None:
    # Committing is the caller's. A resolution that committed on its own would
    # stand after its caller rolled back: an incident reported over, and no
    # account of it saying so.
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert),
                as_it_was := incidents.get(conn, incident_id),
                calling(written_and_rolled_back(
                    conn, lambda: incidents.resolve(conn, incident_id, at=utc_now())
                ))
            ) \
            .when(
                lambda: incidents.get(conn, incident_id)
            ) \
            .then(
                the_answer_was(as_it_was)
            )


def _a_firing(value: str) -> Reference:
    return Reference(source="some-monitor", kind=ALERT_FIRING, value=value)


def _a_step_writing_the_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "summary": SOME_SUMMARY_A_STEP_WROTE}


def _an_incident_written_by_a_newer_argus(conn: psycopg.Connection, alert: Alert) -> str:
    """An incident whose alert is at a shape one on from any this release
    knows, as a newer release would have written it."""
    incident_id = an_incident_created_for(conn, alert)
    conn.execute("UPDATE incident SET shape = %s WHERE id = %s",
                 (SHIPPED.current(ALERT) + 1, incident_id))

    return incident_id


def _its_alert_is(expected: Alert) -> Assertion[Incident | None]:
    def assertion(incident: Incident | None) -> bool:
        if incident is None:
            raise AssertionError("Expected the incident to be read back, got none.")

        if incident.alert != expected:
            raise AssertionError(
                f"Expected the incident's alert to be {expected}, got {incident.alert}."
            )

        return True

    return assertion


def _the_incidents_listed_are(expected: list[str]) -> Assertion[list[Incident]]:
    def assertion(listed: list[Incident]) -> bool:
        listed_ids = [incident.id for incident in listed]

        if sorted(listed_ids) != sorted(expected):
            raise AssertionError(
                f"Expected the incidents listed to be {sorted(expected)}, got "
                f"{sorted(listed_ids)}."
            )

        return True

    return assertion


def _an_incident_holding(conn: psycopg.Connection, service: str, name: Reference) -> str:
    incident_id = an_incident_created_for(conn, Alert(service=service,
                                                      alert_name="HighErrorRate"))
    references.add(conn, incident_id, [name])

    return incident_id


def _it_ended_as(conn: psycopg.Connection, incident_id: str, status: IncidentStatus) -> None:
    """The incident moved to `status` through the door that status comes
    through - or left where it started, for the status it starts in."""
    match status:
        case IncidentStatus.ACKNOWLEDGED:
            pass
        case IncidentStatus.RESOLVED:
            incidents.resolve(conn, incident_id, at=utc_now())
        case IncidentStatus.WITHDRAWN:
            incidents.withdraw(conn, incident_id, at=utc_now())
        case _:
            incidents.transition(conn, incident_id, status, at=utc_now())


def _the_incident_is(conn: psycopg.Connection,
                     status: str,
                     incident_id: str | None = None) -> Assertion[Any]:
    """The status the incident row carries.

    `incident_id` is optional for the reason it is above.
    """
    def assertion(result: Any) -> bool:
        the_incident = incident_id if incident_id is not None else result
        incident = incidents.get(conn, the_incident)

        if incident is None:
            raise AssertionError(f"No incident found with id [{the_incident}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _the_current_incident_was(expected: str) -> Assertion[Incident | None]:
    """Which incident a live view would open on.

    The absence is reported separately from the wrong choice, because the two
    are different failures: nothing current at all is a front page with no
    incident on it, where the wrong one is a front page confidently showing
    somebody the incident they did not come for.
    """
    def assertion(current: Incident | None) -> bool:
        if current is None:
            raise AssertionError(f"Expected incident [{expected}] to be current, got none.")

        if current.id != expected:
            raise AssertionError(
                f"Expected incident [{expected}] to be current, got [{current.id}]."
            )

        return True

    return assertion


def _nothing_came_back() -> Assertion[IncidentStanding | None]:
    """That the repository answered with an absence rather than a row.

    `None` rather than a falsy stand-in: every caller of these two reads asks
    `is None`, and an empty object would sail past that and be rendered as an
    incident with no fields.
    """
    def assertion(found: IncidentStanding | None) -> bool:
        if found is not None:
            raise AssertionError(f"Expected nothing to come back, got [{found}].")

        return True

    return assertion


def _it_found(expected: str) -> Assertion[IncidentStanding | None]:
    """Which incident an alert arriving again would join."""
    def assertion(found: IncidentStanding | None) -> bool:
        if found is None:
            raise AssertionError(f"Expected incident [{expected}] to be found, got none.")

        if found.id != expected:
            raise AssertionError(
                f"Expected incident [{expected}] to be found, got [{found.id}]."
            )

        return True

    return assertion


def _the_incident_records_an_end(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at is None:
            raise AssertionError(
                f"Expected incident [{incident_id}] to record when it ended, got none."
            )

        if incident.ended_at < incident.created_at:
            raise AssertionError(
                f"Expected an end at or after the start [{incident.created_at}], "
                f"got [{incident.ended_at}]."
            )

        return True

    return assertion


def _the_incident_records_no_end(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at is not None:
            raise AssertionError(
                f"Expected incident [{incident_id}] to record no end while it is still "
                f"being worked, got [{incident.ended_at}]."
            )

        return True

    return assertion


def _the_incidents_come_back(conn: psycopg.Connection,
                             newest: str,
                             before: str) -> Assertion[Any]:
    """That one incident is listed before another, wherever the rest are.

    Relative rather than positional: `get_recent` answers with every incident
    there has ever been, so pinning the positions would be an assertion about
    whatever the tests before it left behind.
    """
    def assertion(_result: Any) -> bool:
        listed = [incident.id for incident in incidents.get_recent(conn)]

        for incident_id in (newest, before):
            if incident_id not in listed:
                raise AssertionError(f"Expected [{incident_id}] to come back at all.")

        if listed.index(newest) > listed.index(before):
            raise AssertionError(
                f"Expected [{newest}] before [{before}], the order was {listed}."
            )

        return True

    return assertion


def _a_resolved_incident_for(conn: psycopg.Connection, alert: Alert) -> str:
    incident_id = incidents.create(conn, alert, at=utc_now())
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
        at=utc_now(),
    )

    return incident_id


def _an_incident_at(conn: psycopg.Connection, alert: Alert, status: IncidentStatus) -> str:
    """An incident still being worked, at `status`, committed."""
    incident_id = incidents.create(conn, alert, at=utc_now())
    incidents.transition(conn, incident_id, status, at=utc_now())
    conn.commit()

    return incident_id


def _an_incident_ended_as(conn: psycopg.Connection, alert: Alert, ending: IncidentStatus) -> str:
    """An incident that reached `ending`, committed - its end stamped before
    the resolution that follows gives a later one."""
    incident_id = incidents.create(conn, alert, at=utc_now())
    incidents.transition(conn, incident_id, ending, at=utc_now())
    conn.commit()

    return incident_id


def _the_resolution_reported(expected: bool) -> Assertion[bool]:
    def assertion(resolved: bool) -> bool:
        if resolved != expected:
            raise AssertionError(
                f"Expected the resolution to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{resolved!r}]."
            )

        return True

    return assertion


def _a_withdrawn_incident_for(conn: psycopg.Connection, alert: Alert) -> str:
    incident_id = incidents.create(conn, alert, at=utc_now())
    incidents.withdraw(conn, incident_id, at=utc_now())

    return incident_id


def _it_reported(expected: bool) -> Assertion[bool]:
    def assertion(withdrawn: bool) -> bool:
        if withdrawn != expected:
            raise AssertionError(
                f"Expected the withdrawal to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{withdrawn!r}]."
            )

        return True

    return assertion


def _the_transition_reported(expected: bool) -> Assertion[bool]:
    def assertion(moved: bool) -> bool:
        if moved != expected:
            raise AssertionError(
                f"Expected the transition to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{moved!r}]."
            )

        return True

    return assertion


def _when_it_ended(conn: psycopg.Connection, incident_id: str) -> datetime:
    incident = incidents.get(conn, incident_id)

    assert incident is not None and incident.ended_at is not None

    return incident.ended_at


def _the_incident_opened_at(conn: psycopg.Connection, moment: datetime) -> Assertion[str]:
    def assertion(incident_id: str) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.created_at != moment:
            raise AssertionError(
                f"Expected incident [{incident_id}] to open at [{moment}], got "
                f"[{incident.created_at}]."
            )

        return True

    return assertion


def _the_incident_ended_at(conn: psycopg.Connection,
                           incident_id: str,
                           moment: datetime) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at != moment:
            raise AssertionError(
                f"Expected incident [{incident_id}] to end at [{moment}], got "
                f"[{incident.ended_at}]."
            )

        return True

    return assertion


def _the_incident_still_ended_at(conn: psycopg.Connection,
                                 incident_id: str,
                                 moment: datetime) -> Assertion[bool]:
    """The end an incident already had is not restamped by a second withdrawal.

    How long an incident lasted is a figure Argus reports, and a withdrawal
    that re-stamped it would stretch that figure by however long it took
    somebody to press the button twice.
    """
    def assertion(_withdrawn: bool) -> bool:
        incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.ended_at != moment:
            raise AssertionError(
                f"Expected incident [{incident_id}] to still record its end at "
                f"[{moment}], got [{incident.ended_at}]."
            )

        return True

    return assertion
