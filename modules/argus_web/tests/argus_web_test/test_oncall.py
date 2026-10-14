"""What Argus does with a delivery from the on-call platform.

One thing, and only for one kind of delivery: a person resolved the platform's
incident, so Argus resolves its own - credited to that person, through that
platform, with what they wrote. Everything else the platform says is noted and
left alone, and the reasons are the platform adapter's to give; this suite is
about the matching.

The match is made when the resolution arrives, not when the alert did. Grafana
pages the platform and Argus at the same moment, so at intake the platform's
incident may not exist yet; by the time somebody resolves it, it does. It is
found through the keys its senders stamped on it, and through its own id where
an earlier read already linked it.

A key does not name one incident. Every firing of an alert group pages under the
group's one key, so an alert that stopped and started again leaves two Argus
incidents holding it - and the platform opened a page for each. What tells them
apart is time: the page is about the incidents going on while it was. Never an
older one that merely shares the key, which is how a resolution of today's page
used to resolve last week's incident and leave today's open.

Both parties are stood in for: the platform because it is somebody else's API,
and the incident record because its rows are asserted against a real database
in its own suite.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from argus_core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    Incident,
    IncidentStatus,
    Reference,
    Report,
    ReportChannel,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from argus_web.oncall import IncidentRecord, receive_delivery
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

SOME_PLATFORM_INCIDENT = "Q2FJZEW25HFSAW"
SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_OTHER_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000002"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

# When the page was open: from the moment the platform opened it to the moment
# the person resolved it.
THE_PAGE_OPENED = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
THE_PAGE_RESOLVED = THE_PAGE_OPENED + timedelta(minutes=40)
A_MINUTE = timedelta(minutes=1)

DONT_CARE_BODY = b"{}"
DONT_CARE_HEADERS: dict[str, str] = {}


@pytest.mark.unit
def test_a_persons_resolution_resolves_the_incident_its_keys_name() -> None:
    # The whole of the feature, end to end at this seam: found by key, and
    # credited to the person, through the platform, with their note.
    some_person = "some person"
    some_note = "rolled the flag back by hand"
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by=some_person),
                           keys=[SOME_KEY],
                           note=some_note)
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_it_was_resolved(record, SOME_ARGUS_INCIDENT,
                               Report(by=some_person, channel=ReportChannel.PAGERDUTY,
                                      note=some_note)))


@pytest.mark.unit
def test_the_platforms_incident_becomes_a_name_for_the_argus_incident() -> None:
    # So that the next question about it - engagement, when the postmortem is
    # written - goes straight to it rather than through the keys again.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_it_was_given_the_name(record, SOME_ARGUS_INCIDENT,
                                     Reference(source=ReportChannel.PAGERDUTY,
                                               kind=ON_CALL_INCIDENT,
                                               value=SOME_PLATFORM_INCIDENT)))


@pytest.mark.unit
def test_an_incident_already_linked_to_the_page_is_resolved() -> None:
    # An earlier read matched the two, and that match stands whatever the keys
    # say now.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[])
    record = _a_record(knowing={
        (ON_CALL_INCIDENT, SOME_PLATFORM_INCIDENT): [_an_incident_during_the_page()]
    })

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_these_were_resolved(record, [SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_an_incident_both_linked_and_keyed_is_resolved_once() -> None:
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    the_incident = _an_incident_during_the_page()
    record = _a_record(knowing={(ON_CALL_INCIDENT, SOME_PLATFORM_INCIDENT): [the_incident],
                                (NOTIFICATION_KEY, SOME_KEY): [the_incident]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_these_were_resolved(record, [SOME_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_of_incidents_sharing_the_key_only_the_one_the_page_was_open_for_is_resolved() -> None:
    # The alert fired, Argus escalated, the alert stopped and the platform
    # closed its page; then it fired again, under the same key, and the
    # platform opened another. A person resolving that one is ending today's
    # incident - and last week's, escalated and still resolvable, must stay as
    # it was.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident_over_before_the_page(SOME_OTHER_ARGUS_INCIDENT),
        _an_incident_during_the_page()
    ]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _these_were_resolved(record, [SOME_ARGUS_INCIDENT]),
            _it_was_never_given_a_name(record, SOME_OTHER_ARGUS_INCIDENT)
        ))


@pytest.mark.unit
def test_every_incident_the_page_was_open_for_is_resolved() -> None:
    # Argus said it mitigated the first and the alarm went on, so its reminder
    # opened a second - while the platform kept the one page open across both.
    # The person resolving it is ending both.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident(SOME_OTHER_ARGUS_INCIDENT, IncidentStatus.MITIGATED,
                     created_at=THE_PAGE_OPENED, ended_at=THE_PAGE_OPENED + 10 * A_MINUTE),
        _an_incident(SOME_ARGUS_INCIDENT, IncidentStatus.ESCALATED,
                     created_at=THE_PAGE_OPENED + 20 * A_MINUTE,
                     ended_at=THE_PAGE_OPENED + 25 * A_MINUTE)
    ]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_these_were_resolved(record, [SOME_ARGUS_INCIDENT, SOME_OTHER_ARGUS_INCIDENT]))


@pytest.mark.unit
def test_a_page_opened_after_every_incident_under_its_key_ended_resolves_nothing(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Argus never had today's firing - it arrived nowhere, or was refused -
    # and the key's only holder is an incident that was over before the page
    # opened. Resolving that one would be a person's word reaching the wrong
    # incident.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [
        _an_incident_over_before_the_page(SOME_ARGUS_INCIDENT)
    ]})

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_resolved(record),
            one_record_was_logged(caplog, "argus_web.oncall", logging.INFO,
                                  "on-call resolution matched no incident",
                                  values={"platform_incident": SOME_PLATFORM_INCIDENT})
        ))


@pytest.mark.unit
def test_a_resolution_of_an_incident_argus_never_had_resolves_nothing(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The webhook covers every incident on the services it watches, and Argus
    # opened only some of them.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=["some-key-argus-never-recorded"])
    record = _a_record(knowing={})

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_resolved(record),
            one_record_was_logged(caplog, "argus_web.oncall", logging.INFO,
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
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _nothing_was_resolved(record),
            one_record_was_logged(caplog, "argus_web.oncall", logging.INFO, logged,
                                  values={"platform_incident": SOME_PLATFORM_INCIDENT})
        ))


@pytest.mark.unit
def test_any_other_event_resolves_nothing() -> None:
    platform = _a_platform(saying=Irrelevant(event="incident.annotated"), keys=[SOME_KEY])
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_nothing_was_resolved(record))


@pytest.mark.unit
def test_an_unverified_delivery_is_refused_and_resolves_nothing() -> None:
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    platform.parse_delivery.side_effect = OnCallDeliveryUnverified("forged")
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

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
    # person's word Argus never heard.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    getattr(platform, unreadable).side_effect = OnCallUnavailable("unreachable")
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): [_an_incident_during_the_page()]})

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
    platform.channel = ReportChannel.PAGERDUTY
    platform.parse_delivery.return_value = saying
    platform.keys_of.return_value = keys
    platform.resolution_note.return_value = note
    platform.reported_incident.return_value = ReportedIncident(began_at=THE_PAGE_OPENED,
                                                               ended_at=THE_PAGE_RESOLVED,
                                                               acknowledgements=[])

    return platform


def _an_incident(incident_id: str,
                 status: IncidentStatus,
                 created_at: datetime,
                 ended_at: datetime | None) -> Incident:
    return Incident(id=incident_id, alert_payload={}, status=status,
                    created_at=created_at, ended_at=ended_at)


def _an_incident_during_the_page() -> Incident:
    """`SOME_ARGUS_INCIDENT`, opened with the page and still being worked."""
    return _an_incident(SOME_ARGUS_INCIDENT, IncidentStatus.INVESTIGATING,
                        created_at=THE_PAGE_OPENED + A_MINUTE, ended_at=None)


def _an_incident_over_before_the_page(incident_id: str) -> Incident:
    """An incident Argus escalated, which ended an hour before the page opened."""
    return _an_incident(incident_id, IncidentStatus.ESCALATED,
                        created_at=THE_PAGE_OPENED - 120 * A_MINUTE,
                        ended_at=THE_PAGE_OPENED - 60 * A_MINUTE)


def _a_record(knowing: dict[tuple[str, str], list[Incident]]) -> Any:
    """An incident record holding these names, each as (kind, value) -> its
    holders."""
    record = create_autospec(IncidentRecord, instance=True)

    def incidents_known_as(kind: str, values: list[str]) -> list[Incident]:
        found = {incident.id: incident
                 for value in values
                 for incident in knowing.get((kind, value), [])}

        return list(found.values())

    record.incidents_known_as.side_effect = incidents_known_as
    record.resolve.return_value = True

    return record


def _it_was_resolved(record: Any, incident_id: str, reported: Report) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list != [call(incident_id, reported)]:
            raise AssertionError(
                f"Expected [{incident_id}] resolved as reported by {reported!r}, got "
                f"{record.resolve.call_args_list}."
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
                f"Expected {sorted(incident_ids)} each resolved once, got {resolved}."
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
                f"{record.know_it_as.call_args_list}."
            )

        return True

    return assertion


def _it_was_never_given_a_name(record: Any, incident_id: str) -> Assertion[object]:
    """Not linked to a page it was never about, where engagement would read it."""
    def assertion(_: object) -> bool:
        named = [args for args, _kwargs in record.know_it_as.call_args_list
                 if args[0] == incident_id]

        if named:
            raise AssertionError(
                f"Expected [{incident_id}] to be given no name, got {named}."
            )

        return True

    return assertion


def _nothing_was_resolved(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list:
            raise AssertionError(
                f"Expected nothing resolved, got {record.resolve.call_args_list}."
            )

        return True

    return assertion
