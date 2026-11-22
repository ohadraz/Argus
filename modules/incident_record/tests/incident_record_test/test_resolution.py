"""The door a person tells Argus the incident is over through.

Beside the withdrawal and shaped like it, for the same reason: `web_app` calls
it - and PagerDuty's webhook will - and anything `web_app` can import must
reach nothing that walks a graph.

It publishes, which the repository beneath it does not, and what it publishes
names the person. A resolution is a status change Argus did not decide, and the
account is where every reader - the page, Slack, the postmortem - finds out who
did. So the change and its account are one write: a crash between the two
would leave an incident resolved that no reader is ever told of. And the
account cannot take the change down with it: a person who reported the
incident over has, whether or not the sentence saying so could be written.
"""

from __future__ import annotations

import logging

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from core import utc_now
from core.events import IncidentEvent, Publisher, StatusChanged
from core.models import (
    REVERT_FEATURE_FLAG,
    ActionProgress,
    Alert,
    Claimed,
    FailureMode,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    Report,
    ReportChannel,
    SubjectOpen,
)
from incident_record import PublisherFor
from incident_record.repository import hypotheses, incidents, taken_actions
from incident_record.resolution import resolve_incident
from postgres import connect_from_env

from incident_record_test.framework.assertions import the_account_was_written_inside_the_change
from incident_record_test.framework.transactions import (
    Seen,
    failing_on_its_connection,
    seen_from_both_sides,
)

SOME_REPORT = Report(by="some person", channel=ReportChannel.ARGUS_UI,
                     note="rolled the flag back by hand")
# A report written in a chat platform's thread, by the name its adapter gives it.
SOME_PLATFORM = "Kukichat"
SOME_REPORT_IN_A_THREAD = Report(by="some person", channel=ReportChannel.CHAT_PLATFORM,
                                 platform=SOME_PLATFORM)


@pytest.mark.component
def test_a_resolution_that_took_effect_is_published_with_who_reported_it(
    a_clean_database: None
) -> None:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=_into(published))
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_was_published_as_resolved(published, incident_id, SOME_REPORT)
        ))


@pytest.mark.component
def test_a_resolution_that_changed_nothing_publishes_nothing(a_clean_database: None) -> None:
    # A second press, or a press on an incident somebody withdrew while the page
    # was open. Publishing either would tell every watcher something about the
    # incident that is not true.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        incidents.withdraw(conn, incident_id, at=utc_now())

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=_into(published))
        ) \
        .then(all_of(
            _it_reports(False),
            _nothing_was_published(published)
        ))


@pytest.mark.component
def test_a_resolution_reaches_the_incident_itself(a_clean_database: None) -> None:
    # The publishing above is a narration of a change; this is the change. A
    # walk asks the incident, not the event stream, whether somebody ended it.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=_nobody_is_listening)
        ) \
        .then(
            _the_incident_is(incident_id, IncidentStatus.RESOLVED)
        )


@pytest.mark.component
def test_a_resolution_that_took_effect_is_logged_with_where_it_came_from(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # The response ended at somebody's word, and which door the word came in
    # through is the part of it nothing else in the log records.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO))
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT_IN_A_THREAD, connect_from_env,
                                     publisher_for=_nobody_is_listening)
        ) \
        .then(
            one_record_was_logged(caplog, "incident_record.resolution", logging.INFO,
                                  "incident resolved",
                                  values={"channel": ReportChannel.CHAT_PLATFORM,
                                          "platform": SOME_PLATFORM})
        )


@pytest.mark.component
def test_a_resolution_ends_the_incident_at_the_moment_it_is_published(
    a_clean_database: None
) -> None:
    # The row's end and the account's line are one instant.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=_into(published))
        ) \
        .then(
            _it_ended_when_it_was_said_to(published, incident_id)
        )


@pytest.mark.component
def test_a_resolution_leaves_its_incident_s_subjects_to_later_claims_and_no_other_s(
    a_clean_database: None
) -> None:
    # A person reporting the incident over has its changes in their hands, and
    # Argus never puts back a resolved incident's changes - so what it left
    # standing stops holding its subjects: a later incident's claim on one is
    # claimed. Another incident's changes are that incident's, and still hold.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        another_incident_id = incidents.create(conn, some_alert, at=utc_now())
        _a_flag_change_made_in(conn, incident_id, SOME_FLAG)
        _a_flag_change_made_in(conn, another_incident_id, SOME_OTHER_FLAG)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=_nobody_is_listening)
        ) \
        .then(all_of(
            _a_later_claim_on(SOME_FLAG, is_refused_for=NOBODY),
            _a_later_claim_on(SOME_OTHER_FLAG, is_refused_for=another_incident_id)
        ))


@pytest.mark.component
def test_a_resolution_and_its_account_are_one_write(a_clean_database: None) -> None:
    # Written inside the resolution's own transaction: seen there as resolved,
    # and by nobody else until the change and its account commit together.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    seen: list[Seen] = []

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=seen_from_both_sides(seen, incident_id))
        ) \
        .then(
            the_account_was_written_inside_the_change(seen, IncidentStatus.RESOLVED)
        )


@pytest.mark.component
def test_a_resolution_whose_account_fails_still_resolves(a_clean_database: None) -> None:
    # The account is written inside the resolution's own transaction, so one
    # that fails there must fail alone - not abort the transaction and lose the
    # person's resolution with it.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: resolve_incident(incident_id, SOME_REPORT, connect_from_env,
                                     publisher_for=failing_on_its_connection)
        ) \
        .then(all_of(
            _it_reports(True),
            _the_incident_is(incident_id, IncidentStatus.RESOLVED)
        ))


def _into(published: list[IncidentEvent]) -> PublisherFor:
    """A publisher that keeps what it is told, on whichever connection."""
    def publisher_for(_conn: psycopg.Connection) -> Publisher:
        return published.append

    return publisher_for


# The flags the two incidents' changes were made to.
SOME_FLAG = "kuki-flag"
SOME_OTHER_FLAG = "buki-flag"
# No incident holds a flag open: a later claim on it is claimed.
NOBODY = None


def _a_flag_change_made_in(conn: psycopg.Connection, incident_id: str, flag: str) -> None:
    """A flag switched off for a candidate of the incident, and standing."""
    candidate = Hypothesis(incident_id=incident_id, summary="dont care",
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=0.9,
                           supporting_evidence=[], subject=flag)
    hypotheses.record(conn, candidate)
    taken_actions.claim(conn, incident_id, hypothesis_id=candidate.id,
                        action_type=REVERT_FEATURE_FLAG, subject=flag, at=utc_now())
    taken_actions.advance(conn, incident_id, hypothesis_id=candidate.id,
                          to=ActionProgress.PERFORMED,
                          undo_descriptor=FlagUndo(flag=flag, was_enabled=True))


def _a_later_claim_on(flag: str, *, is_refused_for: str | None) -> Assertion[bool]:
    """What a claim on `flag`, by an incident of its own made afterwards,
    finds: refused, naming the incident `is_refused_for` - or claimed, where
    that is `NOBODY`."""
    def assertion(_resolved: bool) -> bool:
        dont_care_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

        with connect_from_env() as conn:
            a_later_incident = incidents.create(conn, dont_care_alert, at=utc_now())
            candidate = Hypothesis(incident_id=a_later_incident, summary="dont care",
                                   failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                                   confidence=0.9, supporting_evidence=[], subject=flag)
            hypotheses.record(conn, candidate)
            answered = taken_actions.claim(conn, a_later_incident,
                                           hypothesis_id=candidate.id,
                                           action_type=REVERT_FEATURE_FLAG, subject=flag,
                                           at=utc_now())

        found = (isinstance(answered, Claimed) if is_refused_for is NOBODY
                 else answered == SubjectOpen(open_in=is_refused_for))

        if not found:
            wanted = ("claimed" if is_refused_for is NOBODY
                      else f"refused, naming [{is_refused_for}]")
            raise AssertionError(
                f"Expected a later claim on [{flag}] {wanted}, got [{answered}]."
            )

        return True

    return assertion


def _it_ended_when_it_was_said_to(published: list[IncidentEvent],
                                  incident_id: str) -> Assertion[bool]:
    def assertion(_ended: bool) -> bool:
        said_at = [event.at for event in published
                   if isinstance(event, StatusChanged)
                   and event.to_status == IncidentStatus.RESOLVED]

        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        ended_at = incident.ended_at if incident is not None else None
        if said_at != [ended_at]:
            raise AssertionError(
                f"Expected the incident to end at the moment its line says, it ended "
                f"at [{ended_at}] and was said to at {said_at}."
            )

        return True

    return assertion


def _nobody_is_listening(_conn: psycopg.Connection) -> Publisher:
    """A publisher for a case that is not about publishing."""
    def publisher(_event: IncidentEvent) -> None:
        return None

    return publisher


def _it_reports(expected: bool) -> Assertion[bool]:
    def assertion(resolved: bool) -> bool:
        if resolved != expected:
            raise AssertionError(
                f"Expected the resolution to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{resolved!r}]."
            )

        return True

    return assertion


def _the_incident_was_published_as_resolved(
    published: list[IncidentEvent], incident_id: str, reported: Report
) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        resolutions = [
            event for event in published
            if isinstance(event, StatusChanged)
            and event.to_status == IncidentStatus.RESOLVED
        ]

        if len(resolutions) != 1:
            raise AssertionError(
                f"Expected exactly one status change to resolved, got "
                f"{[type(event).__name__ for event in published]}."
            )

        if resolutions[0].incident_id != incident_id:
            raise AssertionError(
                f"Expected the event to name incident [{incident_id}], got "
                f"[{resolutions[0].incident_id}]."
            )

        if resolutions[0].reported != reported:
            raise AssertionError(
                f"Expected the event to carry the report [{reported}], got "
                f"[{resolutions[0].reported}]."
            )

        return True

    return assertion


def _nothing_was_published(published: list[IncidentEvent]) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        if published:
            raise AssertionError(
                f"Expected nothing to be published, got "
                f"{[type(event).__name__ for event in published]}."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[bool]:
    def assertion(_resolved: bool) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion
