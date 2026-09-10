from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.events import (
    ChangesRetrieved,
    FlagChangesRetrieved,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    StatusChanged,
)
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion, Scenario
from argus_web.views.storytelling import LiveIncident, Story, build_live_incident, build_story

"""One incident's whole account of itself, arranged for one screen.

The evidence is gathered here rather than left under the retrievals that
returned it, because an investigation that widens reads the same minutes
several times - and a reader scanning for the minute the errors started should
find one table with that minute in it, not the fourth of six fragments that
each contain a copy.

So most of these are about identity: what counts as the same minute, the same
line, the same change. A bucket is its minute and a log line is its text; a
flag change is a flag *and* a moment, because the flag that moved twice - tried
and then put back - is exactly the one whose second move a reader must not lose.

The rest are about the header: how long the incident has been running, and the
version the page polls against. That version has to change when the content
does and not otherwise, or the page either never updates or updates constantly.
"""

_OPENED_AT = datetime(2026, 8, 30, 10, 15, tzinfo=UTC)

SOME_MINUTE = "2026-08-30T10:14:00Z"
AN_EARLIER_MINUTE = "2026-08-30T10:13:00Z"
SOME_FLAG = "some-ramped-flag"


@pytest.mark.unit
def test_a_running_incident_counts_the_time_since_it_opened() -> None:
    # The header's whole job while an incident runs: how long has this been
    # going on.
    some_minutes_running = 1
    a_moment_later = _OPENED_AT + timedelta(minutes=some_minutes_running)

    Scenario() \
        .given(a_running_incident := _an_incident(IncidentStatus.INVESTIGATING)) \
        .when(lambda: build_live_incident(
            a_running_incident, _nothing_was_published(), now=lambda: a_moment_later
        )) \
        .then(_it_has_been_running_for(some_minutes_running * 60))


@pytest.mark.unit
def test_a_finished_incident_stops_counting_at_the_moment_it_finished() -> None:
    # An elapsed time that kept climbing after the incident ended would report
    # the age of the record rather than the length of the incident.
    some_minutes_it_lasted = 2
    a_finished_incident = _an_incident(IncidentStatus.RESOLVED)
    it_ended_at = _OPENED_AT + timedelta(minutes=some_minutes_it_lasted)
    long_afterwards = _OPENED_AT + timedelta(hours=3)

    Scenario() \
        .given(
            the_transition_that_ended_it := StatusChanged(
                incident_id=a_finished_incident.id,
                at=it_ended_at,
                to_status=IncidentStatus.RESOLVED
            )
        ) \
        .when(lambda: build_live_incident(
            a_finished_incident,
            [the_transition_that_ended_it],
            now=lambda: long_afterwards
        )) \
        .then(_it_has_been_running_for(some_minutes_it_lasted * 60))


@pytest.mark.unit
def test_a_live_incident_is_shown_with_the_alert_it_opened_on() -> None:
    # The header names what fired and where. The row stores the alert as the
    # JSON it was normalized into; a reader gets the alert back.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", severity="critical")

    Scenario() \
        .given(
            an_incident_opened_on_it := _an_incident(
                IncidentStatus.INVESTIGATING, alert=some_alert
            )
        ) \
        .when(lambda: build_live_incident(
            an_incident_opened_on_it, _nothing_was_published(), now=lambda: _OPENED_AT
        )) \
        .then(_it_opened_on(some_alert))


@pytest.mark.unit
def test_a_minute_read_twice_is_shown_once_as_the_later_read_saw_it() -> None:
    # A widening investigation reads overlapping windows. The later read wins
    # because it is the later read that Argus acted on - and a table holding
    # both would show one minute disagreeing with itself.
    what_the_first_read_saw = 0.01
    what_the_second_read_saw = 0.99

    Scenario() \
        .given(
            the_same_minute_read_twice := [
                _metrics_showing(SOME_MINUTE, what_the_first_read_saw),
                _metrics_showing(SOME_MINUTE, what_the_second_read_saw)
            ]
        ) \
        .when(lambda: build_story(the_same_minute_read_twice)) \
        .then(_the_minutes_shown_are([(SOME_MINUTE, what_the_second_read_saw)]))


@pytest.mark.unit
def test_the_minutes_are_shown_in_the_order_they_happened() -> None:
    # They arrive in whatever order the retrievals returned them, and a metrics
    # table out of order is not a metrics table.
    dont_care_error_rate = 0.5

    Scenario() \
        .given(
            a_later_minute_read_first := [
                _metrics_showing(SOME_MINUTE, dont_care_error_rate),
                _metrics_showing(AN_EARLIER_MINUTE, dont_care_error_rate)
            ]
        ) \
        .when(lambda: build_story(a_later_minute_read_first)) \
        .then(_the_minutes_shown_are([
            (AN_EARLIER_MINUTE, dont_care_error_rate), (SOME_MINUTE, dont_care_error_rate)
        ]))


@pytest.mark.unit
def test_the_same_log_line_read_twice_is_shown_once() -> None:
    # A log line is its text: the same line returned by two overlapping windows
    # is one thing the service said, not two.
    some_line = f"{SOME_MINUTE} INFO io-shop: account page rendered"

    Scenario() \
        .given(
            the_same_line_read_twice := [_logs_showing(some_line), _logs_showing(some_line)]
        ) \
        .when(lambda: build_story(the_same_line_read_twice)) \
        .then(_the_lines_shown_are([some_line]))


@pytest.mark.unit
def test_a_flag_that_moved_twice_keeps_both_of_its_moves() -> None:
    # Keyed by flag and moment together, because this is the case the key
    # exists for: a flag Argus tried and then put back moved twice, and the
    # second move is the one saying production was left as it was found.
    Scenario() \
        .given(
            a_flag_tried_and_put_back := [_flag_history([
                FlagChange(flag=SOME_FLAG, enabled=True, occurred_at=AN_EARLIER_MINUTE),
                FlagChange(flag=SOME_FLAG, enabled=False, occurred_at=SOME_MINUTE)
            ])]
        ) \
        .when(lambda: build_story(a_flag_tried_and_put_back)) \
        .then(_the_flag_moves_shown_are([("OFF", "ON"), ("ON", "OFF")]))


@pytest.mark.unit
def test_a_change_channel_that_answered_nothing_still_counts_as_read() -> None:
    # An empty answer from the change channel is a finding - it is what rules a
    # deploy out - and a table that simply did not appear would leave that
    # finding unsaid.
    Scenario() \
        .given(it_was_asked_and_had_nothing := [_changes_showing_nothing()]) \
        .when(lambda: build_story(it_was_asked_and_had_nothing)) \
        .then(_the_changes_were_read(True))


@pytest.mark.unit
def test_a_change_channel_nobody_asked_is_not_reported_as_read() -> None:
    # The distinction the flag exists for: a channel nobody asked leaves the
    # same gap as one that was read and had nothing in it, and a reader who
    # cannot tell them apart cannot tell an incomplete investigation from an
    # inconclusive one.
    Scenario() \
        .given(nobody_asked_about_changes := [_metrics_showing(SOME_MINUTE, 0.5)]) \
        .when(lambda: build_story(nobody_asked_about_changes)) \
        .then(_the_changes_were_read(False))


@pytest.mark.unit
def test_two_polls_showing_the_same_thing_carry_the_same_version() -> None:
    # The page polls every two seconds and almost every poll returns what is
    # already on screen. Re-rendering it anyway destroys everything the reader
    # is doing inside it, so the version has to be steady while the content is
    # - including across the seconds that pass between polls, which is why the
    # elapsed time is not in it.
    an_incident = _an_incident(IncidentStatus.INVESTIGATING)
    some_events = [_metrics_showing(SOME_MINUTE, 0.5)]
    a_poll_later = _OPENED_AT + timedelta(seconds=2)

    Scenario() \
        .given(
            what_the_first_poll_showed := build_live_incident(
                an_incident, some_events, now=lambda: _OPENED_AT
            )
        ) \
        .when(lambda: build_live_incident(
            an_incident, some_events, now=lambda: a_poll_later
        )) \
        .then(_it_is_the_same_version_as(what_the_first_poll_showed))


@pytest.mark.unit
def test_a_poll_that_has_something_new_to_show_carries_a_new_version() -> None:
    # The other half: a version that never changed would be the same as having
    # none at all, and the page would never update.
    an_incident = _an_incident(IncidentStatus.INVESTIGATING)
    what_was_known_before = [_metrics_showing(AN_EARLIER_MINUTE, 0.5)]
    what_is_known_now = [*what_was_known_before, _metrics_showing(SOME_MINUTE, 0.5)]

    Scenario() \
        .given(
            what_the_first_poll_showed := build_live_incident(
                an_incident, what_was_known_before, now=lambda: _OPENED_AT
            )
        ) \
        .when(lambda: build_live_incident(
            an_incident, what_is_known_now, now=lambda: _OPENED_AT
        )) \
        .then(_it_is_a_different_version_from(what_the_first_poll_showed))


def _nothing_was_published() -> list[IncidentEvent]:
    """An incident whose stream is empty - a walk that has not started yet."""
    return []


def _an_incident(status: IncidentStatus, alert: Alert | None = None) -> Incident:
    return Incident(
        id=new_id(),
        alert_payload=(alert or _an_alert()).model_dump(mode="json"),
        status=status,
        slack_channel_id=None,
        pr_url=None,
        created_at=_OPENED_AT,
        ended_at=None
    )


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _metrics_showing(bucket_id: str, error_rate: float) -> MetricsRetrieved:
    """One metrics read that came back with a single minute in it."""
    return MetricsRetrieved(
        incident_id=new_id(),
        window_start=bucket_id,
        window_end=bucket_id,
        buckets=[MetricBucket(
            bucket_id=bucket_id,
            error_rate=error_rate,
            p50_ms=120,
            p95_ms=240,
            request_volume=200
        )]
    )


def _logs_showing(line: str) -> LogsRetrieved:
    return LogsRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        lines=[line]
    )


def _changes_showing_nothing() -> ChangesRetrieved:
    return ChangesRetrieved(
        incident_id=new_id(),
        window_start=AN_EARLIER_MINUTE,
        window_end=SOME_MINUTE,
        changes=[]
    )


def _flag_history(changes: list[FlagChange]) -> FlagChangesRetrieved:
    return FlagChangesRetrieved(incident_id=new_id(), changes=changes)


def _it_has_been_running_for(expected: int) -> Assertion[LiveIncident]:
    def assertion(live: LiveIncident) -> bool:
        if live.elapsed_seconds != expected:
            raise AssertionError(
                f"expected {expected}s elapsed, got {live.elapsed_seconds}s"
            )

        return True

    return assertion


def _it_opened_on(expected: Alert) -> Assertion[LiveIncident]:
    def assertion(live: LiveIncident) -> bool:
        if live.alert != expected:
            raise AssertionError(f"expected the alert [{expected}], got [{live.alert}]")

        return True

    return assertion


def _the_minutes_shown_are(expected: list[tuple[str, float]]) -> Assertion[Story]:
    """The metrics table, whole - each minute with what it showed.

    Asserted as a list rather than a count, because two of the three rules here
    are about order and about which read won, and neither survives being
    checked one row at a time.
    """
    def assertion(story: Story) -> bool:
        shown = [(bucket.bucket_id, bucket.error_rate) for bucket in story.metrics]

        if shown != expected:
            raise AssertionError(f"expected the minutes {expected}, got {shown}")

        return True

    return assertion


def _the_lines_shown_are(expected: list[str]) -> Assertion[Story]:
    def assertion(story: Story) -> bool:
        shown = [log.text for log in story.logs]

        if shown != expected:
            raise AssertionError(f"expected the lines {expected}, got {shown}")

        return True

    return assertion


def _the_flag_moves_shown_are(expected: list[tuple[str, str]]) -> Assertion[Story]:
    def assertion(story: Story) -> bool:
        shown = [(row.was, row.now) for row in story.flag_changes]

        if shown != expected:
            raise AssertionError(f"expected the moves {expected}, got {shown}")

        return True

    return assertion


def _the_changes_were_read(expected: bool) -> Assertion[Story]:
    def assertion(story: Story) -> bool:
        if story.read_changes is not expected:
            raise AssertionError(
                f"expected the change channel to be reported as "
                f"{'read' if expected else 'unread'}, it was not"
            )

        return True

    return assertion


def _it_is_the_same_version_as(earlier: LiveIncident) -> Assertion[LiveIncident]:
    def assertion(live: LiveIncident) -> bool:
        if live.version != earlier.version:
            raise AssertionError(
                f"expected the page to be unchanged at version [{earlier.version}], "
                f"got [{live.version}]"
            )

        return True

    return assertion


def _it_is_a_different_version_from(earlier: LiveIncident) -> Assertion[LiveIncident]:
    def assertion(live: LiveIncident) -> bool:
        if live.version == earlier.version:
            raise AssertionError(
                f"expected a new version, the page still reads [{live.version}]"
            )

        return True

    return assertion
