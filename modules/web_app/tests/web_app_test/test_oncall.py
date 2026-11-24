"""What Argus does with a delivery from the on-call platform.

One thing, and only for one kind of delivery: a person resolved the platform's
incident, so Argus resolves its own - credited to that person, through that
platform, with what they wrote. Everything else the platform says is noted and
left alone, and the reasons are the platform adapter's to give.

Which Argus incidents the page is about is the incident record's to decide, and
its own suite says how. What belongs here is what the record is asked - the
page, its keys, and a way to read when it was open - and what is done with its
answer.

Both parties are stood in for: the platform because it is somebody else's API,
and the incident record because its decisions and rows are asserted in its own
suite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from core.models import ON_CALL_INCIDENT, Lifespan, Reference, Report, ReportChannel
from incident_record import EndedAsSaid
from oncall_source import OnCallUnavailable, ReportedIncident
from oncall_source.platform import (
    Delivery,
    Irrelevant,
    Merged,
    OnCallDeliveryUnverified,
    OnCallPlatform,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)
from web_app.oncall import IncidentRecord, receive_delivery

# The on-call platform's name, as its adapter gives it.
THE_ON_CALL_PLATFORM = "PagerDuty"

SOME_PLATFORM_INCIDENT = "Q2FJZEW25HFSAW"
SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_OTHER_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000002"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

# When the page was open: from the moment the platform opened it to the moment
# the person resolved it.
THE_PAGE_OPENED = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
THE_PAGE_RESOLVED = THE_PAGE_OPENED + timedelta(minutes=40)

DONT_CARE_BODY = b"{}"
DONT_CARE_HEADERS: dict[str, str] = {}
DONT_CARE_PERSON = "dont care"


@pytest.mark.unit
def test_a_persons_resolution_resolves_the_incident_the_page_is_about() -> None:
    # The whole of the feature, end to end at this seam: credited to the
    # person, through the platform, with their note.
    some_person = "some person"
    some_note = "rolled the flag back by hand"
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=some_person),
                           keys=[SOME_KEY],
                           note=some_note)
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_it_was_resolved(record, SOME_ARGUS_INCIDENT,
                               Report(by=some_person, channel=ReportChannel.ON_CALL_PLATFORM,
                                      platform=THE_ON_CALL_PLATFORM,
                                      note=some_note)))


@pytest.mark.unit
def test_the_record_is_asked_about_the_page_with_its_keys_and_when_it_was_open() -> None:
    # The keys are read up front; when the page was open is handed over as a
    # read the record makes only if it needs to, and it reads the platform's
    # own account of the page.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=[SOME_KEY])
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_the_record_was_asked_about(
            record, SOME_PLATFORM_INCIDENT, [SOME_KEY],
            Lifespan(began_at=THE_PAGE_OPENED, ended_at=THE_PAGE_RESOLVED)
        ))


@pytest.mark.unit
def test_the_platforms_incident_becomes_a_name_for_the_argus_incident() -> None:
    # So that the next question about it - engagement, when the postmortem is
    # written - goes straight to it rather than through the keys again.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=[SOME_KEY])
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_it_was_given_the_name(record, SOME_ARGUS_INCIDENT,
                                     Reference(source=THE_ON_CALL_PLATFORM,
                                               kind=ON_CALL_INCIDENT,
                                               value=SOME_PLATFORM_INCIDENT)))


@pytest.mark.unit
def test_every_incident_the_page_is_about_is_resolved() -> None:
    # Argus said it mitigated the first and the alarm went on, so its reminder
    # opened a second - while the platform kept the one page open across both.
    # The person resolving it is ending both.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=[SOME_KEY])
    record = _a_record(about=[SOME_ARGUS_INCIDENT, SOME_OTHER_ARGUS_INCIDENT])

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_these_were_resolved(record, [SOME_ARGUS_INCIDENT, SOME_OTHER_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_a_resolution_of_a_page_about_no_incident_resolves_nothing(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The webhook covers every incident on the services it watches, and Argus
    # opened only some of them.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=["some-key-argus-never-recorded"])
    record = _a_record(about=[])

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_resolved(record),
            one_record_was_logged(caplog, "web_app.oncall", logging.INFO,
                                  "on-call resolution matched no incident",
                                  values={"platform_incident": SOME_PLATFORM_INCIDENT})
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("delivery", "logged"), [
    (ResolvedWithoutAPerson(platform_incident=SOME_PLATFORM_INCIDENT, resolved_by="Events API V2"),
     "on-call resolution not by a person"),
    (Merged(platform_incident=SOME_PLATFORM_INCIDENT, into="Q0N5RRK7RT1Q46"),
     "on-call incident merged"),
    (Reopened(platform_incident=SOME_PLATFORM_INCIDENT),
     "on-call incident reopened")
])
def test_what_is_not_a_persons_resolution_resolves_nothing_and_is_said(
    delivery: Delivery, logged: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Each for its own reason, given where the delivery is read: the monitor
    # clearing its alert is a metrics signal Argus reads for itself, a merge
    # moved the incident rather than ended it, and a reopen after Argus marked
    # the incident resolved does not unsay the person who resolved it.
    platform = _a_platform(saying=delivery, keys=[SOME_KEY])
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_resolved(record),
            one_record_was_logged(caplog, "web_app.oncall", logging.INFO, logged,
                                  values={"platform_incident": SOME_PLATFORM_INCIDENT})
        ))


@pytest.mark.unit
def test_any_other_event_resolves_nothing() -> None:
    platform = _a_platform(saying=Irrelevant(event="incident.annotated"), keys=[SOME_KEY])
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_nothing_was_resolved(record))


@pytest.mark.unit
def test_an_unverified_delivery_is_refused_and_resolves_nothing() -> None:
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=[SOME_KEY])
    platform.parse_delivery.side_effect = OnCallDeliveryUnverified("forged")
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(attempting(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                  platform=platform, record=record))) \
        .then(all_of(
            an_error_was_raised(OnCallDeliveryUnverified),
            _nothing_was_resolved(record)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("unreadable", ["keys_of", "reported_incident"],
                         ids=["its-keys", "when-it-was-open"])
def test_a_platform_that_cannot_be_read_mid_match_resolves_nothing_and_says_so(
    unreadable: str
) -> None:
    # Raised rather than swallowed, so the delivery is answered as a failure
    # and the platform sends it again - a resolution lost to a blip would be a
    # person's word Argus never heard. The record reads when the page was open
    # where a key is held, as the one here does.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=DONT_CARE_PERSON),
                           keys=[SOME_KEY])
    getattr(platform, unreadable).side_effect = OnCallUnavailable("unreachable")
    record = _a_record(about=[SOME_ARGUS_INCIDENT])

    Scenario() \
        .when(attempting(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                  platform=platform, record=record))) \
        .then(all_of(
            an_error_was_raised(OnCallUnavailable),
            _nothing_was_resolved(record)
        ))


def _a_platform(saying: Delivery, keys: list[str], note: str | None = None) -> Any:
    """The platform, holding one page under `keys`, open from
    `THE_PAGE_OPENED` until the person resolved it."""
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.name = THE_ON_CALL_PLATFORM
    platform.parse_delivery.return_value = saying
    platform.keys_of.return_value = keys
    platform.resolution_note.return_value = note
    platform.reported_incident.return_value = ReportedIncident(began_at=THE_PAGE_OPENED,
                                                               ended_at=THE_PAGE_RESOLVED,
                                                               acknowledgements=[])

    return platform


def _a_record(about: list[str]) -> Any:
    """An incident record that says the page is about `about` - reading when
    the page was open first, as the real decision does where a key is held -
    and resolves each incident it is asked to."""
    record = create_autospec(IncidentRecord, instance=True)

    def incidents_a_page_is_about(_page: str,
                                  _keys: list[str],
                                  the_pages_life: Callable[[], Lifespan]) -> list[str]:
        the_pages_life()

        return about

    record.incidents_a_page_is_about.side_effect = incidents_a_page_is_about
    record.resolve.side_effect = lambda incident_id, _reported: EndedAsSaid(incident_id)

    return record


def _the_record_was_asked_about(record: Any,
                                page: str,
                                keys: list[str],
                                open_while: Lifespan) -> Assertion[object]:
    """Asked once, about `page` with `keys`, and handed a read of when it was
    open that answers `open_while`."""
    def assertion(_: object) -> bool:
        asked = record.incidents_a_page_is_about.call_args_list

        if len(asked) != 1:
            raise AssertionError(
                f"Expected the record to be asked about the page once, got {asked}"
            )

        (asked_page, asked_keys, the_pages_life), _kwargs = asked[0]
        read = the_pages_life()

        if (asked_page, list(asked_keys), read) != (page, keys, open_while):
            raise AssertionError(
                f"Expected the record asked about [{page}] with keys {keys} and a page open "
                f"[{open_while}], got [{asked_page}] with keys {list(asked_keys)} and a page "
                f"open [{read}]."
            )

        return True

    return assertion


def _it_was_resolved(record: Any, incident_id: str, reported: Report) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list != [call(incident_id, reported)]:
            raise AssertionError(
                f"Expected [{incident_id}] resolved as reported by {reported!r}, got "
                f"{record.resolve.call_args_list}"
            )

        return True

    return assertion


def _these_were_resolved(record: Any, incident_ids: list[str]) -> Assertion[object]:
    """Each of these resolved once, and nothing else - in no order, since
    nothing about ending several depends on which ends first."""
    def assertion(_: object) -> bool:
        resolved = [args[0] for args, _kwargs in record.resolve.call_args_list]

        if sorted(resolved) != sorted(incident_ids):
            raise AssertionError(
                f"Expected {sorted(incident_ids)} each resolved once, got {resolved}"
            )

        return True

    return assertion


def _it_was_given_the_name(record: Any,
                           incident_id: str,
                           reference: Reference) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if call(incident_id, reference) not in record.know_it_as.call_args_list:
            raise AssertionError(
                f"Expected [{incident_id}] to be given the name {reference!r}, got "
                f"{record.know_it_as.call_args_list}"
            )

        return True

    return assertion


def _nothing_was_resolved(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list:
            raise AssertionError(
                f"Expected nothing resolved, got {record.resolve.call_args_list}"
            )

        return True

    return assertion
