"""What Argus does with a delivery from the on-call platform.

One thing, and only for one kind of delivery: a person resolved the platform's
incident, so Argus resolves its own - credited to that person, through that
platform, with what they wrote. Everything else the platform says is noted and
left alone, and the reasons are the platform adapter's to give; this suite is
about the matching.

The match is made when the resolution arrives, not when the alert did. Grafana
pages the platform and Argus at the same moment, so at intake the platform's
incident may not exist yet; by the time somebody resolves it, it does. It is
found through the keys its senders stamped on it - or, where an earlier read
already linked it, by its own id.

Both parties are stood in for: the platform because it is somebody else's API,
and the incident record because its rows are asserted against a real database
in its own suite.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from argus_core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
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
from oncall_source import OnCallUnavailable
from oncall_source.platform import (
    Delivery,
    DeliveryUnverified,
    Irrelevant,
    Merged,
    OnCallPlatform,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)

SOME_PLATFORM_INCIDENT = "Q2FJZEW25HFSAW"
SOME_ARGUS_INCIDENT = "4c1e2a50-0000-4000-8000-000000000001"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

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
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

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
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_it_was_given_the_name(record, SOME_ARGUS_INCIDENT,
                                     Reference(source=ReportChannel.PAGERDUTY,
                                               kind=ON_CALL_INCIDENT,
                                               value=SOME_PLATFORM_INCIDENT)))


@pytest.mark.unit
def test_an_incident_already_linked_is_found_without_asking_for_its_keys() -> None:
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[])
    record = _a_record(knowing={(ON_CALL_INCIDENT, SOME_PLATFORM_INCIDENT): SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(all_of(
            _it_was_resolved_at_all(record, SOME_ARGUS_INCIDENT),
            _its_keys_were_never_asked_for(platform)
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
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

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
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                       platform=platform, record=record)) \
        .then(_nothing_was_resolved(record))


@pytest.mark.unit
def test_an_unverified_delivery_is_refused_and_resolves_nothing() -> None:
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    platform.read_delivery.side_effect = DeliveryUnverified("forged")
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(attempting(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                  platform=platform, record=record))) \
        .then(all_of(
            an_error_was_raised(DeliveryUnverified),
            _nothing_was_resolved(record)
        ))


@pytest.mark.unit
def test_a_platform_that_cannot_be_read_mid_match_resolves_nothing_and_says_so() -> None:
    # Raised rather than swallowed, so the delivery is answered as a failure
    # and the platform sends it again - a resolution lost to a blip would be a
    # person's word Argus never heard.
    platform = _a_platform(saying=ResolvedByAPerson(platform_incident=SOME_PLATFORM_INCIDENT,
                                                    by="dont care"),
                           keys=[SOME_KEY])
    platform.keys_of.side_effect = OnCallUnavailable("unreachable")
    record = _a_record(knowing={(NOTIFICATION_KEY, SOME_KEY): SOME_ARGUS_INCIDENT})

    Scenario() \
        .when(attempting(lambda: receive_delivery(DONT_CARE_BODY, DONT_CARE_HEADERS,
                                                  platform=platform, record=record))) \
        .then(all_of(
            an_error_was_raised(OnCallUnavailable),
            _nothing_was_resolved(record)
        ))


def _a_platform(saying: Delivery, keys: list[str], note: str | None = None) -> Any:
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.channel = ReportChannel.PAGERDUTY
    platform.read_delivery.return_value = saying
    platform.keys_of.return_value = keys
    platform.resolution_note.return_value = note

    return platform


def _a_record(knowing: dict[tuple[str, str], str]) -> Any:
    """An incident record holding these names, each as (kind, value) -> incident."""
    record = create_autospec(IncidentRecord, instance=True)

    def incident_known_as(kind: str, values: list[str]) -> str | None:
        return next((knowing[(kind, value)] for value in values if (kind, value) in knowing),
                    None)

    record.incident_known_as.side_effect = incident_known_as
    record.resolve.return_value = True

    return record


def _it_was_resolved(record: Any, incident_id: str, reported: Report) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args != call(incident_id, reported):
            raise AssertionError(
                f"Expected [{incident_id}] resolved as reported by {reported!r}, got "
                f"{record.resolve.call_args_list}."
            )

        return True

    return assertion


def _it_was_resolved_at_all(record: Any, incident_id: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        resolved = [args[0] for args, _kwargs in record.resolve.call_args_list]

        if resolved != [incident_id]:
            raise AssertionError(f"Expected [{incident_id}] resolved once, got {resolved}.")

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


def _nothing_was_resolved(record: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if record.resolve.call_args_list:
            raise AssertionError(
                f"Expected nothing resolved, got {record.resolve.call_args_list}."
            )

        return True

    return assertion


def _its_keys_were_never_asked_for(platform: Any) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if platform.keys_of.call_args_list:
            raise AssertionError(
                f"Expected an incident already linked to be found without its keys, "
                f"and they were asked for: {platform.keys_of.call_args_list}."
            )

        return True

    return assertion
